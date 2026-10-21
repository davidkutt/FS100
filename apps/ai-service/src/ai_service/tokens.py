"""kb-ai at Keycloak (ADR-0009): the hop-2 token exchange and its own service token."""

import time

import httpx2

from ai_service.core.settings import Settings

RENEW_EARLY_S = 30  # so a token never expires in flight


class Tokens:
    def __init__(self, settings: Settings) -> None:
        realm = settings.ai_keycloak_realm_url or settings.ai_keycloak_issuer
        self._url = f"{realm}/protocol/openid-connect/token"
        self._client = {
            "client_id": settings.ai_keycloak_client_id,
            "client_secret": settings.ai_keycloak_client_secret,
        }
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}

    async def exchange(self, subject_token: str, scope: str) -> str:
        """The caller's `aud=kb-ai` token for the MCP server; the scopes bring its audience."""
        form = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": scope,
        }
        return await self._cached((subject_token, scope), form)

    async def service_token(self) -> str:
        """kb-ai's service account (client credentials), e.g. for the API's internal routes."""
        return await self._cached(("", "client_credentials"), {"grant_type": "client_credentials"})

    async def _cached(self, key: tuple[str, str], form: dict[str, str]) -> str:
        now = time.monotonic()
        if (hit := self._cache.get(key)) and hit[1] > now:
            return hit[0]
        token, expires_in = await self._fetch(form | self._client)
        # Expired entries go on every fetch, so the cache holds about one entry per active user.
        self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        self._cache[key] = (token, now + expires_in - RENEW_EARLY_S)
        return token

    async def _fetch(self, form: dict[str, str]) -> tuple[str, int]:
        async with httpx2.AsyncClient(timeout=5) as client:
            response = await client.post(self._url, data=form)
        if response.status_code != 200:
            raise RuntimeError(
                f"Keycloak token endpoint: HTTP {response.status_code} {response.text}"
            )
        body = response.json()
        return body["access_token"], body["expires_in"]
