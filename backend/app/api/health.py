from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    # Dependency checks (database, storage, ...) are added as those integrations
    # are introduced. None exist yet, so none are reported.
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    """Readiness: the application has started and can serve requests.

    No external dependencies are verified at this stage.
    """
    return ReadyResponse(status="ready", checks={})
