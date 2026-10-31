from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from canonguard.db.models import LLMCall, Run, Step


def utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid(value: UUID | str) -> UUID:
    """SQLite rejects a str for a Uuid column, Postgres is forgiving; normalise here."""
    return value if isinstance(value, UUID) else UUID(str(value))


class RunLedger:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_run(
        self,
        task: str,
        scope: dict[str, object] | None = None,
        model_config: dict[str, object] | None = None,
        prompt_version: str | None = None,
        thread_id: UUID | None = None,
    ) -> Run:
        with self._session_factory() as session:
            run = Run(
                task=task,
                scope=scope,
                model_config=model_config,
                prompt_version=prompt_version,
                thread_id=thread_id,
                status="queued",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def mark_running(self, run_id: UUID | str) -> None:
        with self._session_factory() as session:
            run = session.get(Run, _uuid(run_id))
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            run.status = "running"
            session.commit()

    def finish_run(
        self,
        run_id: UUID | str,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            run = session.get(Run, _uuid(run_id))
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            run.status = status
            run.error = error
            run.finished_at = utcnow()
            session.commit()

    def start_step(
        self,
        run_id: UUID | str,
        step: str,
        payload: dict[str, object] | None = None,
    ) -> Step:
        with self._session_factory() as session:
            item = Step(
                run_id=_uuid(run_id),
                step=step,
                status="running",
                payload=payload,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def finish_step(
        self,
        step_id: UUID | str,
        status: str = "succeeded",
        payload: dict[str, object] | None = None,
        error: str | None = None,
    ) -> Step:
        with self._session_factory() as session:
            item = session.get(Step, _uuid(step_id))
            if item is None:
                raise KeyError(f"step not found: {step_id}")
            item.status = status
            item.error = error
            item.finished_at = utcnow()
            if payload is not None:
                item.payload = payload
            session.commit()
            session.refresh(item)
            return item

    def get_run(self, run_id: UUID | str) -> Run | None:
        with self._session_factory() as session:
            return session.get(Run, _uuid(run_id))

    def list_steps(self, run_id: UUID | str) -> list[Step]:
        with self._session_factory() as session:
            stmt = select(Step).where(Step.run_id == _uuid(run_id)).order_by(Step.started_at)
            return list(session.scalars(stmt).all())

    def record_llm_call(
        self,
        run_id: UUID | str | None,
        role: str,
        model: str,
        prompt_hash: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: float,
        response_uri: str | None = None,
    ) -> LLMCall:
        with self._session_factory() as session:
            call = LLMCall(
                run_id=_uuid(run_id) if run_id is not None else None,
                role=role,
                model=model,
                prompt_hash=prompt_hash,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                response_uri=response_uri,
            )
            session.add(call)
            session.commit()
            session.refresh(call)
            return call
