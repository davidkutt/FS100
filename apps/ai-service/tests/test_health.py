from fastapi.testclient import TestClient

from ai_service import __version__
from ai_service.core.settings import Settings
from ai_service.main import create_app


def client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_healthz_reports_ok() -> None:
    response = client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_propagated() -> None:
    response = client().get("/healthz", headers={"x-request-id": "req-42"})

    assert response.headers["x-request-id"] == "req-42"


def test_root_describes_the_service() -> None:
    response = client().get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "ai-service", "version": __version__, "docs": "/docs"}


def test_readyz_is_unavailable_before_startup() -> None:
    assert client().get("/readyz").status_code == 503
