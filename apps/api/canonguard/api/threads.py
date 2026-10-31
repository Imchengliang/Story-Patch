"""Conversation endpoints: threads, turns, and the SSE v2 progress stream."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from canonguard.api import deps
from canonguard.core.config import get_settings
from canonguard.core.logging import get_logger
from canonguard.db.models import Run
from canonguard.db.session import SessionLocal
from canonguard.harness.budget import Budget, Usage
from canonguard.harness.bus import event_bus
from canonguard.harness.planner import (
    PIPELINE,
    Plan,
    PlanStep,
    build_plan,
    default_plan,
    should_plan,
)
from canonguard.harness.recorder import RecordingGateway
from canonguard.harness.replay import replay_run
from canonguard.harness.runtime import RunState, TurnInput, stream_turn
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.plot.precedent_view import build_precedent_views
from canonguard.plot.scene_index import SceneIndex
from canonguard.plot.schemas import StuckPoint
from canonguard.plot.story_state import StoryStateService
from canonguard.runs.ledger import RunLedger

router = APIRouter(tags=["threads"])
logger = get_logger(__name__)

_store = ThreadStore(SessionLocal)
_ledger = RunLedger(SessionLocal)
_story = StoryStateService(_store)


RESUME_TOOLS = tuple(name for name in PIPELINE if name != "parse_stuck_point")


class CreateThreadRequest(BaseModel):
    title: str = ""
    story_state: str = ""
    language: str = "unknown"
    characters: list[dict[str, Any]] = Field(default_factory=list)


class ThreadOut(BaseModel):
    id: UUID
    title: str
    story_id: UUID | None = None
    archived: bool = False
    active_stuck: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: UUID
    seq: int
    role: str
    content: str
    payload: dict[str, Any] | None = None
    run_id: UUID | None = None


class ThreadDetail(BaseModel):
    thread: ThreadOut
    messages: list[MessageOut]
    last_run: dict[str, Any] | None = None


class TurnRequest(BaseModel):
    content: str = Field(min_length=1)
    story_state: str = ""
    stuck_question: str = ""
    genre: str = ""
    characters: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_effect: str = ""


class ThreadPatch(BaseModel):
    archived: bool | None = None


class TurnAccepted(BaseModel):
    thread_id: UUID
    run_id: str
    message_seq: int
    streaming: Literal[True] = True


class ReplayAccepted(BaseModel):
    thread_id: UUID
    source_run_id: str
    run_id: str


class StuckPointPatch(BaseModel):
    genre: str | None = None
    current_node: str | None = None
    stuck_question: str | None = None
    constraints: list[str] | None = None
    desired_effect: str | None = None
    narrative_functions: list[str] | None = None
    value_polarity: Literal["positive", "negative", "ironic", "mixed", "unclear"] | None = None


def _thread_out(thread: Any) -> ThreadOut:
    return ThreadOut.model_validate(thread, from_attributes=True)


def _message_out(message: Any) -> MessageOut:
    return MessageOut.model_validate(message, from_attributes=True)


def tool_context(run_id: str, thread_id: UUID) -> ToolContext:
    """Single injection point for services; tests replace this with fakes."""
    try:
        scene_index = deps.scene_index()
    except FileNotFoundError:
        logger.warning("scene_index_missing")
        scene_index = None
    return ToolContext(
        gateway=RecordingGateway(deps.gateway(), _record_llm_call(run_id)),
        aliases=deps.aliases(),
        scene_index=scene_index,
        embedder=deps.embedder(),
        store=_store,
        run_id=run_id,
        thread_id=thread_id,
    )


def _record_llm_call(run_id: str) -> Any:
    def record(role: str, result: Any) -> None:
        _ledger.record_llm_call(
            run_id,
            role,
            result.model,
            None,
            result.prompt_tokens,
            result.completion_tokens,
            result.cost_usd,
            result.latency_ms,
        )

    return record


def _turn_input(request: TurnRequest, thread: Any) -> TurnInput:
    state = ""
    if thread.story_id is not None:
        story = _store.get_story_state(thread.story_id)
        state = story.source_text if story else ""
    return TurnInput(
        story_state=request.story_state or state,
        stuck_question=request.stuck_question or request.content,
        genre=request.genre,
        characters=request.characters,
        constraints=request.constraints,
        desired_effect=request.desired_effect,
    )


def _resume_state(thread: Any) -> RunState | None:
    if not thread.active_stuck:
        return None
    return RunState(stuck=StuckPoint.model_validate(thread.active_stuck))


_ingest_tasks: dict[str, asyncio.Task[None]] = {}


def _start_ingest(story_id: UUID, run_id: str) -> None:
    """Build the story graph in the background; the turn must not block on it."""
    key = str(story_id)
    current = _ingest_tasks.get(key)
    if current is not None and not current.done():
        return

    async def build() -> None:
        try:
            await _story.ingest_story(story_id)
        except Exception as exc:  # noqa: BLE001 - the turn can run without the graph
            logger.warning("story_ingest_failed", story_id=key, run_id=run_id, error=str(exc))

    task = asyncio.create_task(build())
    _ingest_tasks[key] = task

    def _cleanup(_: asyncio.Task[None]) -> None:
        _ingest_tasks.pop(key, None)

    task.add_done_callback(_cleanup)


async def _plan_for(
    thread: Any,
    request: TurnRequest,
    state: RunState | None,
) -> Plan:
    if state is not None:
        had_rejection = any(item.decision == "reject" for item in _store.list_feedback(thread.id))
        if not should_plan(request.content, had_rejection=had_rejection):
            return Plan(
                steps=[
                    PlanStep(tool=name, reason="reuse stored stuck point") for name in RESUME_TOOLS
                ],
                note="resume",
            )
        return await build_plan(
            deps.gateway(),
            default_registry,
            request.content,
            {"stored_stuck_point": True, "precedents": 0, "suggestions": 0},
        )
    return default_plan()


async def _execute_turn(
    thread_id: UUID,
    run_id: str,
    request: TurnRequest,
) -> None:
    thread = _store.get_thread(thread_id)
    if thread is None:  # the thread was archived between accept and run
        return
    ctx = tool_context(run_id, thread_id)
    _ledger.mark_running(run_id)
    event_bus.start(run_id)
    if thread.story_id is not None:
        story = _store.get_story_state(thread.story_id)
        if story is not None and story.kg_group_id is None and story.source_text.strip():
            event_bus.publish(
                run_id,
                "stage",
                {"stage": "ingest", "message": "构建故事图谱…", "run_id": run_id},
            )
            _start_ingest(thread.story_id, run_id)
        stuck = thread.active_stuck or {}
        question = request.stuck_question or str(stuck.get("stuck_question", ""))
        raw_characters = stuck.get("characters")
        characters = raw_characters if isinstance(raw_characters, list) else []
        names = request.characters or [
            str(item.get("name", "")) for item in characters if isinstance(item, dict)
        ]
        query = " ".join([question, request.content, *names]).strip()
        ctx.story_facts = await _story.facts_for(thread.story_id, query)
    state = _resume_state(thread)
    plan = await _plan_for(thread, request, state)

    outcome_ok = False
    collected: dict[str, Any] = {
        "plan": [step.tool for step in plan.steps],
        "story_facts": list(ctx.story_facts),
    }
    pending_done: dict[str, Any] | None = None
    try:
        event_bus.publish(
            run_id, "stage", {"stage": "parse", "message": "解析卡点…", "run_id": run_id}
        )
        async for event, data in stream_turn(
            default_registry,
            ctx,
            _turn_input(request, thread),
            plan,
            state,
            Budget.from_settings(get_settings()),
        ):
            if event == "done":
                outcome_ok = bool(data.get("ok"))
                pending_done = data
                if not outcome_ok:
                    collected["error"] = data.get("error", "")
                continue
            event_bus.publish(run_id, event, data)
            if event == "stuck_point":
                event_bus.publish(
                    run_id,
                    "stage",
                    {"stage": "retrieve", "message": "检索场景…", "run_id": run_id},
                )
                collected["stuck_point"] = data
            elif event == "precedents":
                collected["precedents"] = data.get("hits", [])
                event_bus.publish(
                    run_id,
                    "stage",
                    {"stage": "suggest", "message": "生成建议…", "run_id": run_id},
                )
            elif event == "mapping":
                collected["mapping"] = data
            elif event == "suggestion":
                collected.setdefault("suggestions", []).append(data)
            elif event == "budget":
                collected["usage"] = data
            elif event == "fallback":
                collected["used_fallback"] = True
    except Exception as exc:  # noqa: BLE001 - the run must still be closed out
        logger.exception("thread_turn_failed", thread_id=str(thread_id), run_id=run_id)
        collected["error"] = str(exc)
        event_bus.publish(run_id, "error", {"detail": str(exc)})
    finally:
        run_row = _ledger.get_run(run_id)
        model_config = (run_row.model_config if run_row else None) or {}
        suggestions = collected.get("suggestions", [])
        scene_index: SceneIndex | None
        try:
            scene_index = deps.scene_index()
        except FileNotFoundError:
            scene_index = None
        scene_items = [
            item
            for call in _store.list_tool_calls(run_id)
            if call.name == "retrieve_scenes" and isinstance(call.output, list)
            for item in call.output
            if isinstance(item, dict)
        ]
        precedents = (
            build_precedent_views(scene_index, scene_items, suggestions)
            if scene_index is not None
            else collected.get("precedents", [])
        )
        # Persist the rendered cards (with excerpts) so reloading a thread shows
        # the same precedents as the live stream, not bare hit records.
        collected["precedents"] = precedents
        if outcome_ok:
            event_bus.publish(
                run_id,
                "result",
                {
                    "provider": str(model_config.get("provider", "")),
                    "model": str(model_config.get("model", "")),
                    "stuck_point": collected.get("stuck_point"),
                    "precedents": precedents,
                    "suggestions": suggestions,
                    "story_facts": collected.get("story_facts", []),
                },
            )
        event_bus.publish(
            run_id,
            "done",
            pending_done or {"ok": outcome_ok, "error": collected.get("error", "")},
        )
        event_bus.close(run_id)

    _store.append_message(
        thread_id,
        role="assistant",
        content="",
        payload=collected,
        run_id=UUID(run_id),
    )
    if collected.get("stuck_point"):
        _store.set_active_stuck(thread_id, collected["stuck_point"])
    _ledger.finish_run(
        run_id, "succeeded" if outcome_ok else "failed", error=collected.get("error")
    )


@router.post("/threads", response_model=ThreadOut, status_code=201)
def create_thread(request: CreateThreadRequest) -> ThreadOut:
    story_id = None
    if request.story_state or request.characters:
        story = _store.create_story_state(
            title=request.title or "untitled",
            source_text=request.story_state,
            language=request.language,
            characters=request.characters,
        )
        story_id = story.id
    thread = _store.create_thread(title=request.title, story_id=story_id)
    return _thread_out(thread)


@router.get("/threads", response_model=list[ThreadOut])
def list_threads(include_archived: bool = False) -> list[ThreadOut]:
    return [_thread_out(thread) for thread in _store.list_threads(include_archived)]


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_thread(thread_id: UUID) -> ThreadDetail:
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return ThreadDetail(
        thread=_thread_out(thread),
        messages=[_message_out(message) for message in _store.list_messages(thread_id)],
        last_run=_latest_run(thread_id),
    )


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
def patch_thread(thread_id: UUID, patch: ThreadPatch) -> ThreadOut:
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if patch.archived is None:
        raise HTTPException(status_code=422, detail="no fields to update")
    return _thread_out(_store.set_archived(thread_id, patch.archived))


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: UUID) -> Response:
    """Soft delete: keep runs/messages for audit, hide from the default list."""
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    _store.set_archived(thread_id, True)
    return Response(status_code=204)


def _latest_run(thread_id: UUID) -> dict[str, Any] | None:
    with SessionLocal() as session:
        run = session.scalars(
            select(Run).where(Run.thread_id == thread_id).order_by(Run.created_at.desc()).limit(1)
        ).first()
        if run is None:
            return None
        return {
            "run_id": str(run.id),
            "status": run.status,
            "task": run.task,
            "error": run.error,
        }


class ThreadUsage(BaseModel):
    thread: dict[str, Any]
    runs: list[dict[str, Any]]
    limits: dict[str, Any]


@router.get("/threads/{thread_id}/usage", response_model=ThreadUsage)
def thread_usage(thread_id: UUID) -> ThreadUsage:
    if _store.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    budget = Budget.from_settings(get_settings())
    runs = []
    with SessionLocal() as session:
        recent = session.scalars(
            select(Run).where(Run.thread_id == thread_id).order_by(Run.created_at.desc())
        ).all()
        for run in recent:
            usage = Usage.from_row(_store.usage_for_run(run.id))
            runs.append({"run_id": str(run.id), "task": run.task, **usage.as_dict()})
    total = Usage.from_row(_store.usage_for_thread(thread_id))
    return ThreadUsage(
        thread=total.as_dict(),
        runs=runs,
        limits={"max_tokens": budget.max_tokens, "max_cost_usd": budget.max_cost_usd},
    )


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
def list_messages(thread_id: UUID, limit: int | None = None) -> list[MessageOut]:
    if _store.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return [_message_out(message) for message in _store.list_messages(thread_id, limit=limit)]


@router.post("/threads/{thread_id}/messages", response_model=TurnAccepted, status_code=202)
async def post_message(
    thread_id: UUID,
    request: TurnRequest,
    background_tasks: BackgroundTasks,
) -> TurnAccepted:
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if thread.active_stuck is None and not (request.story_state and request.stuck_question):
        raise HTTPException(
            status_code=422,
            detail=(
                "this thread has no stuck point yet; send story_state and stuck_question "
                "once, then follow up with just your question"
            ),
        )
    message = _store.append_message(thread_id, role="user", content=request.content)
    run = _ledger.create_run("plot_turn", scope={"thread_id": str(thread_id)}, thread_id=thread_id)
    background_tasks.add_task(_execute_turn, thread_id, str(run.id), request)
    return TurnAccepted(thread_id=thread_id, run_id=str(run.id), message_seq=message.seq)


@router.get("/threads/{thread_id}/events")
async def thread_events(thread_id: UUID, run_id: str) -> EventSourceResponse:
    if _store.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if not event_bus.known(run_id):
        raise HTTPException(
            status_code=404,
            detail="run is not streaming; read the thread for its stored result",
        )

    async def emit() -> Any:
        async for event, data in event_bus.stream(run_id):
            yield {"event": event, "data": json.dumps(data, ensure_ascii=False)}

    return EventSourceResponse(emit())


def _turn_before_run(thread: Any, run: Run) -> TurnInput:
    """Recover what triggered a run, for replaying it.

    Prefer the thread's story state; when the thread has none (the draft arrived
    in the first turn's request), fall back to the recorded parse input so replay
    re-runs with the same arguments instead of an empty story.
    """
    messages = _store.list_messages(thread.id)
    user = next(
        (
            message
            for message in reversed(messages)
            if message.role == "user" and message.created_at <= run.created_at
        ),
        None,
    )
    question = user.content if user else ""
    story = _store.get_story_state(thread.story_id) if thread.story_id else None
    story_state = story.source_text if story else ""
    genre = "Drama"
    characters: list[str] = []
    constraints: list[str] = []
    desired_effect = ""
    if not story_state:
        parse_call = next(
            (
                call
                for call in _store.list_tool_calls(str(run.id))
                if call.name == "parse_stuck_point" and isinstance(call.input, dict)
            ),
            None,
        )
        if parse_call is not None:
            recorded: dict[str, Any] = (
                parse_call.input if isinstance(parse_call.input, dict) else {}
            )
            story_state = str(recorded.get("story_state") or "")
            question = str(recorded.get("stuck_question") or question)
            genre = str(recorded.get("genre") or genre)
            raw_characters = recorded.get("characters")
            if isinstance(raw_characters, list):
                characters = [str(item) for item in raw_characters]
            raw_constraints = recorded.get("constraints")
            if isinstance(raw_constraints, list):
                constraints = [str(item) for item in raw_constraints]
            desired_effect = str(recorded.get("desired_effect") or "")
    return TurnInput(
        story_state=story_state,
        stuck_question=question,
        genre=genre,
        characters=characters,
        constraints=constraints,
        desired_effect=desired_effect,
    )


async def _execute_replay(thread_id: UUID, source_run_id: str, run_id: str) -> None:
    source = _ledger.get_run(source_run_id)
    if source is None:
        return
    ctx = tool_context(run_id, thread_id)
    _ledger.mark_running(run_id)
    event_bus.start(run_id)
    ok = False
    error = ""
    try:
        thread = _store.get_thread(thread_id)
        if thread is None:
            return
        report = await replay_run(
            default_registry,
            ctx,
            _turn_before_run(thread, source),
            source_run_id,
            run_id,
            seed=_resume_state(thread),
        )
        ok = report.ok
        error = report.error
        event_bus.publish(
            run_id,
            "replay",
            {
                "source_run_id": report.source_run_id,
                "ok": report.ok,
                "error": report.error,
                "checks": [
                    {
                        "tool": check.tool,
                        "equal": check.equal,
                        "comparable": check.comparable,
                        "detail": check.detail,
                    }
                    for check in report.checks
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001 - the stream must still terminate
        logger.exception("thread_replay_failed", thread_id=str(thread_id), run_id=run_id)
        error = str(exc)
        event_bus.publish(run_id, "error", {"detail": error})
    finally:
        event_bus.publish(run_id, "done", {"ok": ok, "error": error})
        event_bus.close(run_id)
        _ledger.finish_run(run_id, "succeeded" if ok else "failed", error=error or None)


class StoryIngestResult(BaseModel):
    facts: int
    group_id: str = ""


@router.post("/threads/{thread_id}/story/ingest", response_model=StoryIngestResult)
async def ingest_story(thread_id: UUID) -> StoryIngestResult:
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if thread.story_id is None:
        raise HTTPException(status_code=409, detail="this thread has no story draft")
    try:
        result = await _story.ingest_story(thread.story_id)
    except Exception as exc:  # noqa: BLE001 - surface a stable API error
        raise HTTPException(status_code=503, detail=f"story graph unavailable: {exc}") from exc
    return StoryIngestResult(
        facts=int(result.get("facts", 0)), group_id=str(result.get("group_id", ""))
    )


@router.post("/threads/{thread_id}/replay", response_model=ReplayAccepted, status_code=202)
async def replay_thread(
    thread_id: UUID,
    source_run_id: str,
    background_tasks: BackgroundTasks,
) -> ReplayAccepted:
    if _store.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    source = _ledger.get_run(source_run_id)
    if source is None or source.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="source run not found in this thread")
    run = _ledger.create_run(
        "plot_turn_replay",
        scope={"source_run_id": source_run_id},
        thread_id=thread_id,
    )
    background_tasks.add_task(_execute_replay, thread_id, source_run_id, str(run.id))
    return ReplayAccepted(thread_id=thread_id, source_run_id=source_run_id, run_id=str(run.id))


@router.patch("/threads/{thread_id}/stuck-point", response_model=ThreadOut)
def patch_stuck_point(thread_id: UUID, patch: StuckPointPatch) -> ThreadOut:
    thread = _store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    changes = {key: value for key, value in patch.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to update")
    if thread.active_stuck is None:
        raise HTTPException(
            status_code=409,
            detail="the thread has no parsed stuck point yet; run a turn first",
        )
    merged = {**thread.active_stuck, **changes}
    try:
        stuck = StuckPoint.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 - surface the validation reason
        raise HTTPException(status_code=422, detail=f"invalid stuck point: {exc}") from exc
    return _thread_out(_store.set_active_stuck(thread_id, stuck.model_dump()))
