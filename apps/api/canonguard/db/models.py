from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from canonguard.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Work(CreatedAtMixin, Base):
    __tablename__ = "works"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class Edition(CreatedAtMixin, Base):
    __tablename__ = "editions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("works.id"), nullable=False, index=True)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    license_note: Mapped[str | None] = mapped_column(Text)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    edition_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("editions.id"), nullable=False, index=True
    )
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_chapters_edition_order", "edition_id", "order"),)


class Paragraph(Base):
    __tablename__ = "paragraphs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    chapter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("chapters.id"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    edition_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("editions.id"), nullable=False, index=True
    )
    paragraph_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("paragraphs.id"), nullable=False, index=True
    )
    start_cp: Mapped[int] = mapped_column(Integer, nullable=False)
    end_cp: Mapped[int] = mapped_column(Integer, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    chapter_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("chapters.id"), nullable=False, index=True
    )
    start_paragraph: Mapped[int] = mapped_column(Integer, nullable=False)
    end_paragraph: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))


class Gap(CreatedAtMixin, Base):
    __tablename__ = "gaps"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("works.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(1), nullable=False)
    scope: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    interval: Mapped[dict[str, object] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    recommendation: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (Index("ix_gaps_work_type", "work_id", "type"),)


class GapEvidence(Base):
    __tablename__ = "gap_evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    gap_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("gaps.id"), nullable=False, index=True)
    span_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("spans.id"), nullable=False, index=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class GapReview(CreatedAtMixin, Base):
    __tablename__ = "gap_reviews"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    gap_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("gaps.id"), nullable=False, index=True)
    confirmed_type: Mapped[str] = mapped_column(String(1), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="local")


class Conflict(CreatedAtMixin, Base):
    __tablename__ = "conflicts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object_value: Mapped[str | None] = mapped_column("object", String(200))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSON)


class Run(CreatedAtMixin, Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    thread_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("threads.id", name="fk_runs_thread_id"), index=True
    )
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[dict[str, object] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    model_config: Mapped[dict[str, object] | None] = mapped_column(JSON)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id"), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_steps_run_started", "run_id", "started_at"),)


class LLMCall(CreatedAtMixin, Base):
    __tablename__ = "llm_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_uri: Mapped[str | None] = mapped_column(Text)


class Report(CreatedAtMixin, Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("works.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[dict[str, object] | None] = mapped_column(JSON)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="local")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON)


class CanonVersion(CreatedAtMixin, Base):
    __tablename__ = "canon_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    snapshot_uri: Mapped[str] = mapped_column(Text, nullable=False)


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class StoryState(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "story_states"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="untitled")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    characters: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    kg_group_id: Mapped[str | None] = mapped_column(String(200))


class Thread(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "threads"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    story_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("story_states.id"), index=True)
    active_stuck: Mapped[dict[str, object] | None] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)


class Message(CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("uq_messages_thread_seq", "thread_id", "seq", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("threads.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"), index=True)


class StoryFact(CreatedAtMixin, Base):
    __tablename__ = "story_facts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    story_state_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("story_states.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate: Mapped[str] = mapped_column(String(200), nullable=False)
    object: Mapped[str] = mapped_column(String(200), nullable=False)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_span: Mapped[str | None] = mapped_column(Text)


class ToolCall(CreatedAtMixin, Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id"), nullable=False, index=True)
    step_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("steps.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, object] | list[Any] | None] = mapped_column(JSON)
    output_digest: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class SuggestionFeedback(CreatedAtMixin, Base):
    __tablename__ = "suggestion_feedback"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    thread_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("threads.id"), index=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("runs.id"), index=True)
    suggestion_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
