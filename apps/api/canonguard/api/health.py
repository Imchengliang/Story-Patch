import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from canonguard.core.config import get_settings
from canonguard.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    settings = get_settings()
    database_status = "ok"
    database_error: str | None = None
    started = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = "unavailable"
        database_error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "service": settings.app_name,
        "version": "0.1.0",
        "environment": settings.environment,
        "database": {
            "status": database_status,
            "latency_ms": latency_ms,
            "error": database_error,
        },
        "neo4j": {"configured": bool(settings.neo4j_uri)},
        "minio": {"configured": bool(settings.minio_endpoint)},
        "timestamp": datetime.now(UTC).isoformat(),
    }
