from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_service.core.settings import Settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Caller:
    """Whom a request acts for: the user of an exchanged token, or a service account (ADR-0009)."""

    sub: str
    roles: list[str]
    token: str  # the bearer itself, exchanged again for the MCP server (hop 2)

    @classmethod
    def of(cls, claims: dict[str, Any], token: str) -> "Caller":
        return cls(claims["sub"], claims.get("realm_access", {}).get("roles", []), token)


class Jwt:
    """Keycloak access tokens for one audience."""

    def __init__(self, settings: Settings, audience: str) -> None:
        self._issuer = settings.ai_keycloak_issuer
        self._audience = audience
        realm = settings.ai_keycloak_realm_url or self._issuer
        self._jwks = jwt.PyJWKClient(f"{realm}/protocol/openid-connect/certs")

    def decode(self, token: str) -> dict[str, Any]:
        """Blocking: the first call (and an unknown `kid`) fetches the JWKS."""
        key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )


class ServiceAuth:
    """Dependency that admits only Keycloak access tokens for this service (`aud=kb-ai`, D36)."""

    def __init__(self, settings: Settings) -> None:
        self._jwt = Jwt(settings, settings.ai_keycloak_audience)

    # Sync on purpose: PyJWKClient fetches with blocking I/O, so FastAPI runs this in a thread.
    def __call__(
        self,
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Caller:
        try:
            if credentials is None:
                raise jwt.InvalidTokenError("Missing bearer token")
            claims = self._jwt.decode(credentials.credentials)
        except jwt.PyJWTError as error:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(error), {"WWW-Authenticate": "Bearer"}
            ) from error
        request.state.caller = caller = Caller.of(claims, credentials.credentials)
        return caller


def get_caller(request: Request) -> Caller:
    """The caller `ServiceAuth` admitted; every /v1 router runs it first."""
    return request.state.caller


def require_admin(request: Request) -> None:
    """For admin routes: the exchanged user token must carry the realm role `admin`."""
    if "admin" not in get_caller(request).roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
