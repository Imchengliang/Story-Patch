import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from canonguard.db.models import Run, Step


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _step_payload(step: Step) -> dict[str, object]:
    return {
        "id": str(step.id),
        "name": step.step,
        "status": step.status,
        "started_at": _iso(step.started_at),
        "finished_at": _iso(step.finished_at),
        "error": step.error,
        "payload": step.payload,
    }


async def step_event_stream(
    session_factory: sessionmaker[Session],
    run_id: UUID,
    poll_interval: float = 0.2,
) -> AsyncIterator[dict[str, str]]:
    seen: dict[str, str] = {}
    while True:
        with session_factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": "run not found"}, ensure_ascii=False),
                }
                return

            steps = session.scalars(
                select(Step).where(Step.run_id == run_id).order_by(Step.started_at)
            ).all()
            for step in steps:
                signature = f"{step.status}:{_iso(step.finished_at)}"
                key = str(step.id)
                if seen.get(key) == signature:
                    continue
                seen[key] = signature
                yield {
                    "event": "step",
                    "data": json.dumps(
                        {
                            "run_id": str(run.id),
                            "status": run.status,
                            "step": _step_payload(step),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }

            if run.status in {"succeeded", "failed", "cancelled"}:
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "run_id": str(run.id),
                            "status": run.status,
                            "error": run.error,
                        },
                        ensure_ascii=False,
                    ),
                }
                return

        await asyncio.sleep(poll_interval)
