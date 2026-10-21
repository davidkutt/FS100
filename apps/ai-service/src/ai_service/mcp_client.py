"""MCP client for the own server (ADR-0010): every call carries the caller's hop-2 token."""

from typing import Any

import httpx2
from mcp import Client, types
from mcp.client.context import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client

from ai_service.core.auth import Caller
from ai_service.tokens import Tokens

PROTOCOL = "2026-07-28"  # pinned, so no call pays for a discovery round trip


class McpClient:
    # Tests route the HTTP hop into the app itself (an ASGI transport).
    transport: httpx2.AsyncBaseTransport | None = None

    def __init__(self, url: str, tokens: Tokens) -> None:
        self.url = url
        self.tokens = tokens

    async def call(
        self, caller: Caller, tool: str, args: dict[str, Any], *, write: bool = False
    ) -> types.CallToolResult:
        """A write gets `kb:write` and confirms the server's confirmation request: the harness
        only runs writes the user approved (ADR-0008)."""
        token = await self.tokens.exchange(caller.token, "kb:read kb:write" if write else "kb:read")

        async def confirm(
            context: ClientRequestContext, params: types.ElicitRequestParams
        ) -> types.ElicitResult:
            if write:
                return types.ElicitResult(action="accept", content={"confirm": True})
            return types.ElicitResult(action="decline")

        headers = {"authorization": f"Bearer {token}"}
        # shortcut: a client per call also lists the tools each time (to validate the output
        # schema); keep clients per turn and cache lists with the client manager (M2.5)
        async with (
            httpx2.AsyncClient(headers=headers, transport=self.transport, timeout=30) as http,
            Client(
                streamable_http_client(self.url, http_client=http),
                mode=PROTOCOL,
                elicitation_callback=confirm,
            ) as client,
        ):
            return await client.call_tool(tool, args)
