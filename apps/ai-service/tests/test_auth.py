import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ai_service.core.settings import Settings
from ai_service.main import create_app
from support import fetch_jwks, token

FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_jwks)
    return TestClient(create_app(Settings()))


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        f"Bearer {token(aud='kb-api')}",
        f"Bearer {token(expires_in=-60)}",
        f"Bearer {token(key=FOREIGN_KEY)}",
    ],
    ids=["no token", "wrong audience", "expired", "foreign signature"],
)
def test_status_rejects_invalid_tokens(client: TestClient, authorization: str | None) -> None:
    headers = {"Authorization": authorization} if authorization else {}

    response = client.get("/v1/status", headers=headers)

    assert response.status_code == 401


def test_status_accepts_a_service_token(client: TestClient) -> None:
    response = client.get("/v1/status", headers={"Authorization": f"Bearer {token()}"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "qdrant": "down"}  # no lifespan, so no Qdrant
