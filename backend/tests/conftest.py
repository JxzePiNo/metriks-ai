from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(app_env="test", log_level="WARNING")
    # The context manager runs the app lifespan (startup/shutdown).
    with TestClient(create_app(settings)) as c:
        yield c
