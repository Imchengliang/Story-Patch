from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from canonguard.core.logging import get_logger


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str | None = None


class CanonGuardError(Exception):
    def __init__(
        self,
        title: str,
        detail: str,
        status_code: int = 400,
        code: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.code = code


def register_exception_handlers(app: FastAPI) -> None:
    logger = get_logger(__name__)

    @app.exception_handler(CanonGuardError)
    async def canon_guard_error_handler(_request: Request, exc: CanonGuardError) -> JSONResponse:
        problem = ProblemDetail(
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            code=exc.code,
        )
        return JSONResponse(status_code=exc.status_code, content=problem.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        problem = ProblemDetail(
            title="Internal Server Error",
            status=500,
            detail="An unexpected error occurred.",
            code="internal_error",
        )
        return JSONResponse(status_code=500, content=problem.model_dump())
