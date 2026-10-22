"""MCP client (ADR-0010) for the own server and the external ones (`config/mcp_servers.yaml`)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp import Client, types
from mcp.client.caching import CacheConfig, InMemoryResponseCacheStore
from mcp.client.context import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client

PROTOCOL = "2026-07-28"  # pinned, so no call pays for a discovery round trip


class McpClient:
    """One server. A client per call, all sharing one response cache, so `tools/list` runs once
    per partition and the server's `ttlMs` (the GitHub server sends 0: every turn lists)."""

    # Tests route the HTTP hop into an app (an ASGI transport).
    transport: httpx2.AsyncBaseTransport | None = None

    def __init__(self, url: str, timeout_s: float = 30) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self._cache = InMemoryResponseCacheStore()

    async def call(
        self,
        token: str,
        tool: str,
        args: dict[str, Any],
        *,
        partition: str = "service",
        write: bool = False,
    ) -> types.CallToolResult:
        """A write confirms the server's confirmation request: the harness only runs writes the
        user approved (ADR-0008)."""
        async with self._connect(token, partition, write) as client:
            # The output-schema check after the call lists through the session, past the cache;
            # a cached listing first gives the session the schemas without a round trip.
            await client.list_tools()
            return await client.call_tool(tool, args)

    async def list_tools(self, token: str, partition: str = "service") -> list[types.Tool]:
        async with self._connect(token, partition) as client:
            # shortcut: first page only; follow `next_cursor` once a server pages its tools
            return (await client.list_tools()).tools

    @asynccontextmanager
    async def _connect(
        self, token: str, partition: str, write: bool = False
    ) -> AsyncGenerator[Client]:
        async def confirm(
            context: ClientRequestContext, params: types.ElicitRequestParams
        ) -> types.ElicitResult:
            if write:
                return types.ElicitResult(action="accept", content={"confirm": True})
            return types.ElicitResult(action="decline")

        # `partition` separates callers whose listings may differ (the caller's `sub`).
        # The SDK cannot tell the server from a transport object, hence `target_id`.
        cache = CacheConfig(store=self._cache, partition=partition, target_id=self.url)
        headers = {"authorization": f"Bearer {token}"}
        async with (
            httpx2.AsyncClient(
                headers=headers, transport=self.transport, timeout=self.timeout_s
            ) as http,
            Client(
                streamable_http_client(self.url, http_client=http),
                mode=PROTOCOL,
                elicitation_callback=confirm,
                cache=cache,
            ) as client,
        ):
            yield client
