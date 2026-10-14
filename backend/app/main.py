import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
        yield
        logger.info("Shutting down %s", settings.app_name)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
