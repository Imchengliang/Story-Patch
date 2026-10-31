from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from canonguard.core.config import get_settings
from canonguard.core.logging import get_logger
from canonguard.db.models import Run
from canonguard.db.session import SessionLocal, get_session
from canonguard.runs.checkpoint import get_checkpointer
from canonguard.runs.graph import run_demo
from canonguard.runs.ledger import RunLedger
from canonguard.runs.sse import step_event_stream

router = APIRouter(tags=["runs"])
logger = get_logger(__name__)
_checkpointer = get_checkpointer(get_settings().database_url)


def _run_demo_background(ledger: RunLedger, run_id: str) -> None:
    try:
        run_demo(ledger, run_id, checkpointer=_checkpointer)
    except Exception:
        logger.exception("demo_run_failed", run_id=run_id)


@router.post("/runs/demo", status_code=202)
def create_demo_run(background_tasks: BackgroundTasks) -> dict[str, str]:
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run(
        task="demo",
        scope={"kind": "phase0"},
        prompt_version="phase0",
    )
    background_tasks.add_task(_run_demo_background, ledger, str(run.id))
    return {"run_id": str(run.id), "status": run.status}


@router.get("/runs/{run_id}")
def get_run(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": str(run.id),
        "task": run.task,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


@router.get("/runs/{run_id}/events")
def run_events(run_id: UUID) -> EventSourceResponse:
    return EventSourceResponse(step_event_stream(SessionLocal, run_id))
