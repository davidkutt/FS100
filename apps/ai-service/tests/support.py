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

MARKDOWN = b"# Runbook\n\n## Rollback\nUndo the release with kubectl rollout undo.\n"
USER = {"sub": "carol", "roles": ["viewer"]}
SIGNING_KEY = "test-only-approval-signing-key-0123456789"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS: dict[str, Any] = {
    "keys": [{**RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "test"}]
}


def fetch_jwks(_self: jwt.PyJWKClient) -> dict[str, Any]:
    return JWKS


def token(aud: str = "kb-ai", expires_in: int = 300, key: rsa.RSAPrivateKey = KEY) -> str:
    now = int(time.time())
    claims = {"iss": Settings().ai_keycloak_issuer, "aud": aud, "iat": now, "exp": now + expires_in}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


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
