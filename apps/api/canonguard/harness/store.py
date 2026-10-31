"""Persistence helpers for conversations, story state, and tool accounting."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from canonguard.db.models import (
    LLMCall,
    Message,
    Run,
    StoryFact,
    StoryState,
    SuggestionFeedback,
    Thread,
    ToolCall,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class ThreadStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_story_state(
        self,
        title: str,
        source_text: str = "",
        language: str = "unknown",
        characters: list[dict[str, Any]] | None = None,
    ) -> StoryState:
        with self._session_factory() as session:
            state = StoryState(
                title=title,
                source_text=source_text,
                language=language,
                characters=characters or [],
            )
            session.add(state)
            session.commit()
            session.refresh(state)
            return state

    def get_story_state(self, story_id: UUID | str) -> StoryState | None:
        with self._session_factory() as session:
            return session.get(StoryState, _as_uuid(story_id))

    def find_ingested_story(self, source_text: str) -> StoryState | None:
        text = source_text.strip()
        if not text:
            return None
        with self._session_factory() as session:
            stmt = (
                select(StoryState)
                .where(StoryState.source_text == text, StoryState.kg_group_id.is_not(None))
                .order_by(StoryState.updated_at.desc())
                .limit(1)
            )
            return session.scalars(stmt).first()

    def set_kg_group(self, story_state_id: UUID | str, group_id: str) -> StoryState:
        with self._session_factory() as session:
            state = session.get(StoryState, _as_uuid(story_state_id))
            if state is None:
                raise KeyError(f"story state not found: {story_state_id}")
            state.kg_group_id = group_id
            session.commit()
            session.refresh(state)
            return state

    def create_thread(
        self,
        title: str = "",
        story_id: UUID | None = None,
        active_stuck: dict[str, Any] | None = None,
    ) -> Thread:
        with self._session_factory() as session:
            thread = Thread(title=title, story_id=story_id, active_stuck=active_stuck)
            session.add(thread)
            session.commit()
            session.refresh(thread)
            return thread

    def get_thread(self, thread_id: UUID | str) -> Thread | None:
        with self._session_factory() as session:
            return session.get(Thread, _as_uuid(thread_id))

    def list_threads(self, include_archived: bool = False) -> list[Thread]:
        with self._session_factory() as session:
            stmt = select(Thread).order_by(Thread.updated_at.desc())
            if not include_archived:
                stmt = stmt.where(Thread.archived.is_(False))
            return list(session.scalars(stmt).all())

    def set_active_stuck(self, thread_id: UUID | str, stuck: dict[str, Any]) -> Thread:
        with self._session_factory() as session:
            thread = session.get(Thread, _as_uuid(thread_id))
            if thread is None:
                raise KeyError(f"thread not found: {thread_id}")
            thread.active_stuck = stuck
            thread.updated_at = utcnow()
            session.commit()
            session.refresh(thread)
            return thread

    def set_archived(self, thread_id: UUID | str, archived: bool) -> Thread:
        with self._session_factory() as session:
            thread = session.get(Thread, _as_uuid(thread_id))
            if thread is None:
                raise KeyError(f"thread not found: {thread_id}")
            thread.archived = archived
            thread.updated_at = utcnow()
            session.commit()
            session.refresh(thread)
            return thread

    def archive_thread(self, thread_id: UUID | str) -> Thread:
        return self.set_archived(thread_id, True)

    def append_message(
        self,
        thread_id: UUID | str,
        role: str,
        content: str = "",
        payload: dict[str, Any] | None = None,
        run_id: UUID | None = None,
    ) -> Message:
        """Append with a gapless per-thread sequence number."""
        with self._session_factory() as session:
            thread_uuid = _as_uuid(thread_id)
            if session.get(Thread, thread_uuid) is None:
                raise KeyError(f"thread not found: {thread_id}")
            next_seq = session.scalar(
                select(func.coalesce(func.max(Message.seq), 0)).where(
                    Message.thread_id == thread_uuid
                )
            )
            message = Message(
                thread_id=thread_uuid,
                seq=int(next_seq or 0) + 1,
                role=role,
                content=content,
                payload=payload,
                run_id=run_id,
            )
            session.add(message)
            session.commit()
            session.refresh(message)
            return message

    def list_messages(self, thread_id: UUID | str, limit: int | None = None) -> list[Message]:
        """Messages in sequence order; ``limit`` keeps the most recent window."""
        with self._session_factory() as session:
            thread_uuid = _as_uuid(thread_id)
            if limit is None:
                stmt = select(Message).where(Message.thread_id == thread_uuid)
                return list(session.scalars(stmt.order_by(Message.seq.asc())).all())
            tail = (
                select(Message)
                .where(Message.thread_id == thread_uuid)
                .order_by(Message.seq.desc())
                .limit(limit)
            )
            return list(reversed(list(session.scalars(tail).all())))

    def get_message_by_run(self, thread_id: UUID | str, run_id: UUID | str) -> Message | None:
        """The assistant message produced by a run (latest if several)."""
        with self._session_factory() as session:
            stmt = (
                select(Message)
                .where(
                    Message.thread_id == _as_uuid(thread_id),
                    Message.run_id == _as_uuid(run_id),
                )
                .order_by(Message.seq.desc())
                .limit(1)
            )
            return session.scalars(stmt).first()

    def update_message_payload(self, message_id: UUID | str, payload: dict[str, Any]) -> Message:
        with self._session_factory() as session:
            message = session.get(Message, _as_uuid(message_id))
            if message is None:
                raise KeyError(f"message not found: {message_id}")
            message.payload = payload
            session.commit()
            session.refresh(message)
            return message

    def record_tool_call(
        self,
        run_id: UUID | str,
        name: str,
        input: dict[str, Any],
        step_id: UUID | None = None,
    ) -> ToolCall:
        with self._session_factory() as session:
            call = ToolCall(
                run_id=_as_uuid(run_id),
                step_id=step_id,
                name=name,
                input=input,
            )
            session.add(call)
            session.commit()
            session.refresh(call)
            return call

    def finish_tool_call(
        self,
        call_id: UUID | str,
        status: str = "succeeded",
        output_digest: str = "",
        output: Any | None = None,
        error: str | None = None,
    ) -> ToolCall:
        with self._session_factory() as session:
            call = session.get(ToolCall, _as_uuid(call_id))
            if call is None:
                raise KeyError(f"tool call not found: {call_id}")
            call.status = status
            call.output_digest = output_digest
            if output is not None:
                call.output = output
            call.error = error
            call.finished_at = utcnow()
            session.commit()
            session.refresh(call)
            return call

    def list_tool_calls(self, run_id: UUID | str) -> list[ToolCall]:
        with self._session_factory() as session:
            stmt = (
                select(ToolCall)
                .where(ToolCall.run_id == _as_uuid(run_id))
                .order_by(ToolCall.created_at.asc())
            )
            return list(session.scalars(stmt).all())

    def usage_for_run(self, run_id: UUID | str) -> Any:
        with self._session_factory() as session:
            return session.execute(
                select(
                    func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMCall.completion_tokens), 0),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                    func.count(LLMCall.id),
                ).where(LLMCall.run_id == _as_uuid(run_id))
            ).one()

    def usage_for_thread(self, thread_id: UUID | str) -> Any:
        with self._session_factory() as session:
            return session.execute(
                select(
                    func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMCall.completion_tokens), 0),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                    func.count(LLMCall.id),
                )
                .join(Run, Run.id == LLMCall.run_id)
                .where(Run.thread_id == _as_uuid(thread_id))
            ).one()

    def replace_story_facts(
        self,
        story_state_id: UUID | str,
        facts: list[dict[str, Any]],
    ) -> int:
        """Mirror the graph facts so the thread still works when Neo4j is down."""
        with self._session_factory() as session:
            state_id = _as_uuid(story_state_id)
            for existing in session.scalars(
                select(StoryFact).where(StoryFact.story_state_id == state_id)
            ).all():
                session.delete(existing)
            for fact in facts:
                session.add(
                    StoryFact(
                        story_state_id=state_id,
                        subject=str(fact.get("subject", "")),
                        predicate=str(fact.get("predicate", "")),
                        object=str(fact.get("object", "")),
                        source_span=fact.get("source_span"),
                    )
                )
            session.commit()
            return len(facts)

    def list_story_facts(self, story_state_id: UUID | str) -> list[StoryFact]:
        with self._session_factory() as session:
            stmt = select(StoryFact).where(StoryFact.story_state_id == _as_uuid(story_state_id))
            return list(session.scalars(stmt).all())

    def record_feedback(
        self,
        suggestion_ref: str,
        decision: str,
        thread_id: UUID | str | None = None,
        run_id: UUID | str | None = None,
        reason_code: str | None = None,
        note: str | None = None,
    ) -> SuggestionFeedback:
        with self._session_factory() as session:
            feedback = SuggestionFeedback(
                suggestion_ref=suggestion_ref,
                decision=decision,
                thread_id=_as_uuid(thread_id) if thread_id else None,
                run_id=_as_uuid(run_id) if run_id else None,
                reason_code=reason_code,
                note=note,
            )
            session.add(feedback)
            session.commit()
            session.refresh(feedback)
            return feedback

    def list_feedback(self, thread_id: UUID | str | None = None) -> list[SuggestionFeedback]:
        with self._session_factory() as session:
            stmt = select(SuggestionFeedback).order_by(SuggestionFeedback.created_at.asc())
            if thread_id is not None:
                stmt = stmt.where(SuggestionFeedback.thread_id == _as_uuid(thread_id))
            return list(session.scalars(stmt).all())

    def feedback_summary(self) -> dict[str, Any]:
        """Table-backed summary; JSONL is only an export."""
        rows = self.list_feedback()
        decisions = Counter(row.decision for row in rows)
        reasons = Counter(row.reason_code or "other" for row in rows)
        total = len(rows)
        adopt = decisions.get("adopt", 0)
        return {
            "total": total,
            "decisions": dict(decisions),
            "reasons": dict(reasons),
            "adoption_rate": round(adopt / total, 3) if total else 0.0,
        }


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
