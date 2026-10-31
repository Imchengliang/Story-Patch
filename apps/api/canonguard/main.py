from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from canonguard.api.health import router as health_router
from canonguard.api.plot import router as plot_router
from canonguard.api.runs import router as runs_router
from canonguard.api.threads import router as threads_router
from canonguard.core.config import get_settings
from canonguard.core.errors import register_exception_handlers
from canonguard.core.logging import configure_logging, get_logger
from canonguard.db.session import create_all


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.environment)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_tables:
            try:
                create_all()
            except Exception:
                logger.exception("database_init_failed")
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/v1")
    app.include_router(runs_router, prefix="/v1")
    app.include_router(plot_router, prefix="/v1")
    app.include_router(threads_router, prefix="/v1")
    return app


app = create_app()
