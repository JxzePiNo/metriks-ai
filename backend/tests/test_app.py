from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_app_starts_and_exposes_openapi(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert {"/health", "/ready"} <= set(response.json()["paths"])


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_validation_errors_use_error_envelope() -> None:
    app = create_app(Settings(app_env="test", log_level="WARNING"))

    @app.get("/_items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    with TestClient(app) as client:
        response = client.get("/_items/abc")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unhandled_errors_do_not_leak_details() -> None:
    app = create_app(Settings(app_env="test", log_level="CRITICAL"))

    @app.get("/_boom")
    def boom() -> None:
        raise RuntimeError("secret detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
