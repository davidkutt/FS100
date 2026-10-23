import json
import re
import time
import zlib
from collections.abc import Iterator
from typing import Any

import httpx2
import jwt
import numpy as np
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from numpy.typing import NDArray

from ai_service.core.settings import Settings
from ai_service.routing import Route
from ai_service.tokens import Tokens

MARKDOWN = b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n"
SIGNING_KEY = "test-only-approval-signing-key-0123456789"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS: dict[str, Any] = {
    "keys": [{**RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "test"}]
}


def fetch_jwks(_self: jwt.PyJWKClient) -> dict[str, Any]:
    return JWKS


def token(
    aud: str = "kb-ai",
    expires_in: int = 300,
    key: rsa.RSAPrivateKey = KEY,
    sub: str = "carol",
    roles: tuple[str, ...] = ("viewer",),
    scope: str = "",
) -> str:
    now = int(time.time())
    claims = {
        "iss": Settings().ai_keycloak_issuer,
        "aud": aud,
        "sub": sub,
        "realm_access": {"roles": list(roles)},
        "scope": scope,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


async def exchange(_self: Tokens, form: dict[str, str]) -> tuple[str, int]:
    """Keycloak's token endpoint as the realm answers kb-ai (ADR-0009): same user, MCP audience."""
    if form["grant_type"] == "client_credentials":
        return token(aud="kb-api", sub="service-account-kb-ai", roles=()), 300
    subject = jwt.decode(form["subject_token"], options={"verify_signature": False})
    roles = tuple(subject["realm_access"]["roles"])
    mcp = Settings().mcp_resource_url
    return token(aud=mcp, sub=subject["sub"], roles=roles, scope=form["scope"]), 300


class FixedRouter:
    """Routes every question the same way; unset = low confidence, i.e. every tool, no filter."""

    def __init__(self, route: Route | None = None) -> None:
        self._route = route or Route([], True, 0.0, "embedding")

    async def route(self, question: str) -> Route:
        return self._route


class FakeTextEmbedding:
    """Offline stand-in for fastembed: hashed bag of words, so shared words mean similar vectors."""

    embedding_size = 64

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> Iterator[NDArray[np.float64]]:
        for text in texts:
            self.texts.append(text)
            vector = np.zeros(self.embedding_size)
            for word in re.findall(r"\w+", text.lower()):
                vector[zlib.crc32(word.encode()) % self.embedding_size] += 1
            yield vector


def sse(response: httpx2.Response) -> list[tuple[str, Any]]:
    """`(event, data)` pairs of an SSE response."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = [
        dict(line.split(": ", 1) for line in b.splitlines()) for b in response.text.split("\n\n")
    ]
    return [(b["event"], json.loads(b["data"])) for b in blocks if b]
