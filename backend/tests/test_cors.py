from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ORIGIN = "http://localhost:3000"


def _client(origins: list[str]) -> TestClient:
    settings = Settings(app_env="test", log_level="WARNING", cors_origins=origins)
    return TestClient(create_app(settings))


def test_allowed_origin_gets_cors_header() -> None:
    response = _client([ORIGIN]).get("/health", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_other_origin_gets_no_cors_header() -> None:
    response = _client([ORIGIN]).get("/health", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_allowed_origin() -> None:
    response = _client([ORIGIN]).options(
        "/health",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_cors_disabled_by_default() -> None:
    response = _client([]).get("/health", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers
