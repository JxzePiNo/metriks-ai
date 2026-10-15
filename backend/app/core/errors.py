import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _error(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, **extra}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Return every error as {"error": {"code": ..., "message": ...}}."""

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return _error(
                exc.status_code,
                exc.detail.get("code", f"http_{exc.status_code}"),
                exc.detail.get("message", "Request failed"),
                **{k: v for k, v in exc.detail.items() if k not in {"code", "message"}},
            )
        return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return _error(
            422, "validation_error", "Request validation failed", details=details
        )

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "internal_error", "Internal server error")
