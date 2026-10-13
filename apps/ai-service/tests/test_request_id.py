import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from ai_service.core.settings import Settings
from ai_service.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_mints_a_uuid_when_none_is_sent(client: TestClient) -> None:
    response = client.get("/")

    assert uuid.UUID(response.headers["x-request-id"]).version == 4


def test_echoes_a_safe_incoming_id(client: TestClient) -> None:
    response = client.get("/", headers={"x-request-id": "req-123"})

    assert response.headers["x-request-id"] == "req-123"


@pytest.mark.parametrize("bad", ["has space", "x" * 129, "semi;colon"])
def test_replaces_an_unsafe_incoming_id(client: TestClient, bad: str) -> None:
    response = client.get("/", headers={"x-request-id": bad})

    assert response.headers["x-request-id"] != bad


def test_logs_one_structured_line_per_request(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="ai_service.request"):
        client.get("/", headers={"x-request-id": "req-log"})

    [record] = [r for r in caplog.records if r.name == "ai_service.request"]
    assert record.getMessage() == "request completed"
    assert vars(record).items() >= {
        ("request_id", "req-log"),
        ("method", "GET"),
        ("path", "/"),
        ("status", 200),
    }


def test_does_not_log_probes(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="ai_service.request"):
        client.get("/healthz")

    assert not [r for r in caplog.records if r.name == "ai_service.request"]
