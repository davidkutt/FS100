from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_service.core.settings import Settings

_bearer = HTTPBearer(auto_error=False)


class ServiceAuth:
    """Dependency that admits only Keycloak access tokens for this service (`aud=kb-ai`, D5)."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.ai_keycloak_issuer
        self._audience = settings.ai_keycloak_audience
        self._jwks = jwt.PyJWKClient(f"{self._issuer}/protocol/openid-connect/certs")

    # Sync on purpose: PyJWKClient fetches with blocking I/O, so FastAPI runs this in a thread.
    def __call__(
        self, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
    ) -> dict[str, Any]:
        try:
            if credentials is None:
                raise jwt.InvalidTokenError("Missing bearer token")
            key = self._jwks.get_signing_key_from_jwt(credentials.credentials)
            return jwt.decode(
                credentials.credentials,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as error:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(error), {"WWW-Authenticate": "Bearer"}
            ) from error
