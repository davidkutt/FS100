"""Fixture MCP servers (D43): the pinned GitHub MCP server's tools, answered from seeded scenarios.

After bumping the image, re-record its listing from the running container (`pnpm stack:up`) with
`uv run python -m ai_service.evals.fixtures`; the contract test compares the two.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, TypeAdapter
from starlette.applications import Starlette

from ai_service.catalog import load_servers
from ai_service.core.settings import Settings
from ai_service.mcp_client import McpClient
from ai_service.tools import ToolOutput

FIXTURES = Path("../../evals/fixtures")
REPO = "davidkutt/FS100"  # the repository the scenarios describe
SANDBOX = "davidkutt/fs-100-sandbox"
FAKE_PAT = "ghp_" + "0" * 36  # the server checks the format only before an API call (ADR-0010)
_LISTED = {"name", "description", "input_schema", "annotations"}  # what the model sees
_tools = TypeAdapter(list[types.Tool])


class Reply(BaseModel):
    """A seeded answer to `tool` (as the model names it) for calls whose args contain `match`."""

    tool: str
    match: dict[str, Any] = {}
    result: Any


async def record(url: str, allow: list[str]) -> list[dict[str, Any]]:
    """The server's listing of the allowed tools; a renamed or dropped tool goes missing."""
    tools = {tool.name: tool for tool in await McpClient(url).list_tools(FAKE_PAT)}
    return [
        tools[name].model_dump(mode="json", by_alias=True, exclude_none=True, include=_LISTED)
        for name in allow
        if name in tools
    ]


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)


def _invalid(tool: types.Tool, args: dict[str, Any]) -> str | None:
    """Required, unknown and enum arguments; enough to tell a well-formed call (no types)."""
    properties: dict[str, Any] = tool.input_schema.get("properties", {})
    if missing := [key for key in tool.input_schema.get("required", []) if key not in args]:
        return f"missing required parameter: {', '.join(missing)}"
    if unknown := [key for key in args if key not in properties]:
        return f"unknown parameter: {', '.join(unknown)}"
    for key, value in args.items():
        if "enum" in properties[key] and value not in properties[key]["enum"]:
            return f"invalid value for {key}: {value}"
    return None


class GitHubFixture:
    """The GitHub MCP server as an in-process app: the pinned tool list, seeded answers.

    `replies` is the current scenario; a call nothing matches gets GitHub's 404."""

    def __init__(self, fixtures: Path) -> None:
        self.fixtures = fixtures
        self.tools = _tools.validate_json((fixtures / "github_mcp/tools.json").read_bytes())
        self.replies = self.scenario(None)
        by_name = {tool.name: tool for tool in self.tools}

        async def list_tools(
            _ctx: Any, _params: types.PaginatedRequestParams | None
        ) -> types.ListToolsResult:
            return types.ListToolsResult(tools=self.tools)

        async def call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
            args = params.arguments or {}
            if (tool := by_name.get(params.name)) is None:
                return _error(f"unknown tool {params.name}")
            if problem := _invalid(tool, args):
                return _error(problem)
            if "repo" in args and f"{args.get('owner')}/{args['repo']}".lower() != REPO.lower():
                return _error("404 Not Found")
            if (found := self.reply(f"github.{params.name}", args)) is None:
                return _error("404 Not Found")
            return types.CallToolResult(content=[types.TextContent(type="text", text=found)])

        self.server = Server("github-fixture", on_list_tools=list_tools, on_call_tool=call_tool)
        # The agent's client keeps the configured URL (any host); only the transport changes.
        self.app: Starlette = self.server.streamable_http_app(
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

    def scenario(self, name: str | None) -> list[Reply]:
        """The scenario's replies first, then the repository's everyday state (`base`)."""
        files = [name, "base"] if name else ["base"]
        path = self.fixtures / "scenarios"
        return [
            Reply.model_validate(reply)
            for file in files
            for reply in json.loads((path / f"{file}.json").read_text("utf-8"))
        ]

    def reply(self, tool: str, args: dict[str, Any]) -> str | None:
        found = next(
            (
                reply
                for reply in self.replies
                if reply.tool == tool and all(args.get(k) == v for k, v in reply.match.items())
            ),
            None,
        )
        if found is None:
            return None
        if isinstance(found.result, str):
            return found.result
        return json.dumps(found.result, ensure_ascii=False)

    async def fetch(self, url: str) -> ToolOutput:
        """`web.fetch` without the web: the scenario's page, else the host's 404."""
        if (page := self.reply("web.fetch", {"url": url})) is None:
            raise RuntimeError("HTTP 404")
        return ToolOutput(f"{url}\n\n{page}", f"{len(page):,} chars")


if __name__ == "__main__":
    github = load_servers(Settings().mcp_servers_config)["github"]
    listing = asyncio.run(record(github.url, github.allow))
    target = FIXTURES / "github_mcp/tools.json"
    target.write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"{len(listing)} of {len(github.allow)} allowed tools → {target.resolve()}")
