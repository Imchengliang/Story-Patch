import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from canonguard.api import deps
from canonguard.core.config import get_settings
from canonguard.core.logging import get_logger
from canonguard.db.session import SessionLocal
from canonguard.harness.recorder import RecordingGateway
from canonguard.harness.runtime import TurnInput, stream_turn
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.llm.gateway import (
    LiteLLMCompleter,
    ModelEndpoint,
    RoleConfig,
    StructuredGateway,
)
from canonguard.llm.providers import (
    load_endpoints,
    load_model_endpoints,
    to_litellm_model,
)
from canonguard.plot.aliases import AliasTable
from canonguard.plot.embedding import OllamaEmbedder, load_embedding_config
from canonguard.plot.feedback import (
    SuggestionFeedback,
    append_feedback,
    load_feedback,
    suggestion_id_for_values,
    summarize_feedback,
)
from canonguard.plot.precedent_view import build_precedent_views
from canonguard.plot.schemas import BeatSequence, PlotSuggestion, StuckPoint
from canonguard.plot.story_state import StoryStateService
from canonguard.runs.ledger import RunLedger

router = APIRouter(tags=["plot"])
_story = StoryStateService(ThreadStore(SessionLocal))
_feedback_store = ThreadStore(SessionLocal)
_feedback_ledger = RunLedger(SessionLocal)
logger = get_logger(__name__)


class LlmChoice(BaseModel):
    provider: Literal["auto", "qwen", "deepseek", "custom"] = "auto"
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class SuggestRequest(BaseModel):
    story_state: str = Field(min_length=1)
    stuck_question: str = Field(min_length=1)
    genre: str = ""
    characters: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_effect: str = ""
    precedents: int = Field(default=3, ge=1, le=5)
    candidate_k: int = Field(default=20, ge=1, le=100)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    llm: LlmChoice | None = None


class PrecedentSummary(BaseModel):
    kind: Literal["scene"] = "scene"
    work_title: str
    scene_heading: str
    score: float
    excerpt: str = ""
    highlight: str | None = None
    reasons: list[str] = Field(default_factory=list)


class SuggestResponse(BaseModel):
    run_id: str = ""
    provider: str
    model: str
    stuck_point: StuckPoint
    precedents: list[PrecedentSummary]
    suggestions: list[PlotSuggestion]
    story_facts: list[str] = Field(default_factory=list)
    story_status: Literal["ready", "building", "absent"] = "absent"


FeedbackDecision = Literal["adopt", "modify", "reject"]
FeedbackReason = Literal[
    "structure_mismatch",
    "character_mismatch",
    "world_conflict",
    "cliche",
    "low_novelty",
    "other",
]


class FeedbackRequest(BaseModel):
    suggestion_id: str = ""
    decision: FeedbackDecision
    reason_code: FeedbackReason = "other"
    note: str = ""
    stuck_question: str = ""
    corpus_reference: str = ""
    next_node: str = ""
    thread_id: UUID | None = None
    run_id: UUID | None = None


class BeatRequest(BaseModel):
    stuck: StuckPoint
    suggestion: PlotSuggestion
    scene_id: str = Field(min_length=1)
    thread_id: UUID | None = None
    source_run_id: UUID | None = None


class FeedbackSummary(BaseModel):
    total: int
    decisions: dict[str, int]
    reasons: dict[str, int]
    adoption_rate: float


class IndexInfo(BaseModel):
    scenes: int
    embedding_dim: int
    embed_model: str


def _repo_root() -> Path:
    return deps.repo_root()


def _feedback_path() -> Path:
    return _repo_root() / "data" / "evaluations" / "suggestion_feedback.jsonl"


def _gateway() -> StructuredGateway:
    return deps.gateway()


def _embedder() -> OllamaEmbedder:
    return deps.embedder()


def _aliases() -> AliasTable:
    return deps.aliases()


def _single_endpoint_gateway(
    endpoint: ModelEndpoint,
    writer_temperature: float = 0.6,
) -> StructuredGateway:
    settings = get_settings()
    completer = LiteLLMCompleter(timeout_seconds=settings.llm_request_timeout_seconds)
    roles = {
        "extractor": RoleConfig(
            model=endpoint.model,
            temperature=0.0,
            max_output_tokens=8192,
            api_base=endpoint.api_base,
            api_key=endpoint.api_key,
        ),
        "writer": RoleConfig(
            model=endpoint.model,
            temperature=writer_temperature,
            max_output_tokens=8192,
            api_base=endpoint.api_base,
            api_key=endpoint.api_key,
        ),
        "judge": RoleConfig(
            model=endpoint.model,
            temperature=0.0,
            max_output_tokens=8192,
            api_base=endpoint.api_base,
            api_key=endpoint.api_key,
        ),
    }
    return StructuredGateway(
        roles=roles,
        completer=completer,
        max_repairs=settings.llm_max_repairs,
    )


def _display_model(model: str) -> str:
    return model.removeprefix("openai/")


def _auto_model_label() -> str:
    primary, fallback = load_model_endpoints(get_settings().model_preference)
    if primary and fallback:
        return f"{_display_model(primary.model)} → {_display_model(fallback.model)}"
    if primary:
        return _display_model(primary.model)
    return "server default"


def _gateway_for_choice(
    choice: LlmChoice | None,
) -> tuple[StructuredGateway, str, str]:
    if choice is None or choice.provider == "auto":
        return _gateway(), "auto", _auto_model_label()

    if choice.provider == "qwen":
        primary = load_endpoints().qwen
        if primary is None:
            raise HTTPException(status_code=503, detail="Qwen endpoint is not configured")
        return _single_endpoint_gateway(primary), "qwen", _display_model(primary.model)

    if choice.provider == "deepseek":
        fallback = load_endpoints().deepseek
        if fallback is None:
            raise HTTPException(status_code=503, detail="DeepSeek endpoint is not configured")
        return (
            _single_endpoint_gateway(fallback),
            "deepseek",
            _display_model(fallback.model),
        )

    if not choice.base_url or not choice.model:
        raise HTTPException(
            status_code=422,
            detail="custom provider requires base_url and model",
        )
    endpoint = ModelEndpoint(
        name="custom",
        model=to_litellm_model(choice.model),
        api_base=choice.base_url,
        api_key=choice.api_key or "local",
    )
    return _single_endpoint_gateway(endpoint), "custom", choice.model


async def _suggest_events(
    request: SuggestRequest,
    story_facts: list[str] | None = None,
    story_status: str = "absent",
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Scene-text backend: dense + BM25 over raw scenes, no structural labels."""
    try:
        scene_index = deps.scene_index()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Scene index not found; run `make build-scene-index`",
        ) from exc

    gateway, provider, model = _gateway_for_choice(request.llm)
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run(
        task="plot_suggest",
        scope={
            "mode": "raw",
            "story_chars": len(request.story_state),
            "characters": request.characters,
            "precedents": request.precedents,
        },
        model_config={"provider": provider, "model": model},
        prompt_version=get_settings().prompt_version,
    )
    run_id = str(run.id)
    ledger.mark_running(run_id)

    def record(role: str, result: Any) -> None:
        ledger.record_llm_call(
            run_id,
            role,
            result.model,
            None,
            result.prompt_tokens,
            result.completion_tokens,
            result.cost_usd,
            result.latency_ms,
        )

    ctx = ToolContext(
        gateway=RecordingGateway(gateway, record),
        aliases=_aliases(),
        scene_index=scene_index,
        embedder=_embedder(),
        store=ThreadStore(SessionLocal),
        run_id=run_id,
    )
    turn = TurnInput(
        story_state=request.story_state,
        stuck_question=request.stuck_question,
        genre=request.genre,
        characters=request.characters,
        constraints=request.constraints,
        desired_effect=request.desired_effect,
    )

    stuck: StuckPoint | None = None
    suggestions: list[PlotSuggestion] = []
    yield "stage", {"stage": "parse", "message": "解析卡点…", "run_id": run_id}
    try:
        async for event, data in stream_turn(default_registry, ctx, turn):
            if event == "stuck_point":
                stuck = StuckPoint.model_validate(data)
                yield "stage", {"stage": "embed", "message": "生成查询向量…", "run_id": run_id}
                yield "stage", {"stage": "retrieve", "message": "检索场景…", "run_id": run_id}
            elif event == "precedents":
                yield "stage", {"stage": "suggest", "message": "生成建议…", "run_id": run_id}
            elif event == "suggestion":
                suggestions.append(PlotSuggestion.model_validate(data))
            elif event == "done" and not data.get("ok"):
                raise RuntimeError(str(data.get("error", "raw pipeline failed")))
    except Exception as exc:  # noqa: BLE001 - surface a stable API error
        ledger.finish_run(run_id, "failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"raw suggestion failed: {exc}") from exc

    if stuck is None or not suggestions:
        ledger.finish_run(run_id, "failed", error="no suggestions")
        raise HTTPException(status_code=422, detail="no suggestions found")

    # scenes were emitted as precedents; recover them from the ledger for the response
    scene_items = [
        item
        for call in ctx.store.list_tool_calls(run_id)  # type: ignore[union-attr]
        if call.name == "retrieve_scenes" and isinstance(call.output, list)
        for item in call.output
        if isinstance(item, dict)
    ]
    precedents = [
        PrecedentSummary(**view)
        for view in build_precedent_views(scene_index, scene_items, suggestions)
    ]
    response = SuggestResponse(
        run_id=run_id,
        provider=provider,
        model=model,
        stuck_point=stuck,
        precedents=precedents,
        suggestions=suggestions,
        story_facts=story_facts or [],
        story_status=story_status,
    )
    ledger.finish_run(run_id, "succeeded")
    yield "result", response.model_dump()
    yield "done", {}


async def _story_facts_for(
    request: SuggestRequest,
    background_tasks: BackgroundTasks,
) -> tuple[list[str], str]:
    """Reuse an already-ingested draft; build the graph in the background on first use."""
    text = (request.story_state or "").strip()
    if not text:
        return [], "absent"
    store = ThreadStore(SessionLocal)
    state = store.find_ingested_story(text)
    if state is None:
        created = store.create_story_state(title="auto", source_text=text)
        background_tasks.add_task(_ingest_story_background, created.id)
        return [], "building"
    query = " ".join([request.stuck_question, request.desired_effect, *request.characters]).strip()
    return await _story.facts_for(state.id, query), "ready"


async def _ingest_story_background(story_state_id: Any) -> None:
    try:
        await _story.ingest_story(story_state_id)
    except Exception as exc:  # noqa: BLE001 - the graph is optional for a turn
        logger.warning("story_ingest_failed", story_state_id=str(story_state_id), error=str(exc))


@router.post("/plot/suggest", response_model=SuggestResponse)
async def suggest_plot(
    request: SuggestRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    facts, status = await _story_facts_for(request, background_tasks)
    result: dict[str, Any] | None = None
    async for event, data in _suggest_events(request, facts, status):
        if event == "result":
            result = data
    if result is None:
        raise HTTPException(status_code=500, detail="suggestion pipeline produced no result")
    return result


@router.post("/plot/suggest/stream")
async def suggest_plot_stream(
    request: SuggestRequest,
    background_tasks: BackgroundTasks,
) -> EventSourceResponse:
    facts, status = await _story_facts_for(request, background_tasks)

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        try:
            async for event, data in _suggest_events(request, facts, status):
                yield {
                    "event": event,
                    "data": json.dumps(data, ensure_ascii=False),
                }
        except HTTPException as exc:
            yield {
                "event": "error",
                "data": json.dumps({"detail": exc.detail}, ensure_ascii=False),
            }
        except Exception as exc:  # noqa: BLE001 - stream must terminate cleanly
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


def _feedback_summary_table() -> FeedbackSummary:
    return FeedbackSummary(**_feedback_store.feedback_summary())


def _feedback_summary_jsonl() -> FeedbackSummary:
    return FeedbackSummary(**summarize_feedback(load_feedback(_feedback_path())))


@router.post("/plot/feedback", response_model=FeedbackSummary)
def submit_feedback(request: FeedbackRequest) -> FeedbackSummary:
    suggestion_id = request.suggestion_id or suggestion_id_for_values(
        request.corpus_reference, request.next_node
    )
    if request.thread_id is not None and _feedback_store.get_thread(request.thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if request.run_id is not None and _feedback_ledger.get_run(str(request.run_id)) is None:
        raise HTTPException(status_code=404, detail="run not found")
    # The table is the authority: it can be joined to thread/run. JSONL stays as
    # the export that `make feedback-suggestions` reads.
    _feedback_store.record_feedback(
        suggestion_id,
        request.decision,
        thread_id=request.thread_id,
        run_id=request.run_id,
        reason_code=request.reason_code,
        note=request.note,
    )
    append_feedback(
        _feedback_path(),
        SuggestionFeedback(
            suggestion_id=suggestion_id,
            decision=request.decision,
            reason_code=request.reason_code,
            note=request.note,
            stuck_question=request.stuck_question,
            corpus_reference=request.corpus_reference,
            next_node=request.next_node,
        ),
    )
    return _feedback_summary_table()


def _persist_beats(request: BeatRequest, sequence: BeatSequence) -> None:
    """Attach the beats to the assistant message, aligned with suggestions."""
    if request.thread_id is None or request.source_run_id is None:
        return
    message = _feedback_store.get_message_by_run(request.thread_id, request.source_run_id)
    if message is None:
        return
    payload = dict(message.payload or {})
    raw_suggestions = payload.get("suggestions")
    suggestions: list[object] = list(raw_suggestions) if isinstance(raw_suggestions, list) else []
    index = next(
        (
            position
            for position, item in enumerate(suggestions)
            if isinstance(item, dict)
            and item.get("corpus_reference") == request.suggestion.corpus_reference
            and item.get("next_node") == request.suggestion.next_node
        ),
        None,
    )
    if index is None:
        return
    raw_beats = payload.get("beats")
    beats: list[object] = list(raw_beats) if isinstance(raw_beats, list) else []
    if len(beats) < len(suggestions):
        beats.extend([None] * (len(suggestions) - len(beats)))
    beats[index] = sequence.model_dump(mode="json")
    payload["beats"] = beats
    _feedback_store.update_message_payload(message.id, payload)


@router.post("/plot/beats", response_model=BeatSequence)
async def expand_suggestion(request: BeatRequest) -> BeatSequence:
    try:
        scene_index = deps.scene_index()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="scene index unavailable") from exc
    if request.thread_id is not None and _feedback_store.get_thread(request.thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")

    ledger = RunLedger(SessionLocal)
    run = ledger.create_run(
        task="expand_beats",
        scope={
            "scene_id": request.scene_id,
            "source_run_id": str(request.source_run_id) if request.source_run_id else None,
        },
        model_config={"provider": "auto", "role": "writer"},
        prompt_version=get_settings().prompt_version,
        thread_id=request.thread_id,
    )
    run_id = str(run.id)
    ledger.mark_running(run_id)

    def record(role: str, result: Any) -> None:
        ledger.record_llm_call(
            run_id,
            role,
            result.model,
            None,
            result.prompt_tokens,
            result.completion_tokens,
            result.cost_usd,
            result.latency_ms,
        )

    ctx = ToolContext(
        gateway=RecordingGateway(deps.gateway(), record),
        aliases=_aliases(),
        scene_index=scene_index,
        store=ThreadStore(SessionLocal),
        run_id=run_id,
        thread_id=request.thread_id,
    )
    try:
        result = await default_registry.call(
            "expand_beats",
            {
                "stuck": request.stuck.model_dump(mode="json"),
                "suggestion": request.suggestion.model_dump(mode="json"),
                "scene_id": request.scene_id,
            },
            ctx,
        )
    except Exception as exc:  # noqa: BLE001 - the run must end in a known state
        ledger.finish_run(run_id, "failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"expand_beats failed: {exc}") from exc

    if not result.ok:
        ledger.finish_run(run_id, "failed", error=result.error)
        raise HTTPException(status_code=502, detail=f"expand_beats failed: {result.error}")
    ledger.finish_run(run_id, "succeeded")
    sequence = (
        result.value
        if isinstance(result.value, BeatSequence)
        else BeatSequence.model_validate(result.value)
    )
    _persist_beats(request, sequence)
    return sequence


@router.get("/plot/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(source: Literal["table", "jsonl"] = "table") -> FeedbackSummary:
    if source == "jsonl":
        return _feedback_summary_jsonl()
    return _feedback_summary_table()


@router.get("/plot/index", response_model=IndexInfo)
def index_info() -> IndexInfo:
    try:
        index = deps.scene_index()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Scene index not found; run `make build-scene-index`",
        ) from exc
    config = load_embedding_config()
    return IndexInfo(
        scenes=len(index),
        embedding_dim=index.dim,
        embed_model=config.model,
    )
