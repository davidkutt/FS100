"""Model registry, tool catalog with external MCP servers, and taxonomy (D30, D38, D40, D48)."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, get_args

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from ai_service import catalog
from ai_service.catalog import McpServers, ServerConfig, load_models, load_servers, load_taxonomy
from ai_service.core.settings import Settings
from ai_service.knowledge_base import Domain
from ai_service.tools import JsonArgs, ToolOutput, ToolSpec, registry


def test_committed_config_files_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_MCP_URL", raising=False)
    taxonomy = load_taxonomy(Settings().taxonomy_config)
    models = load_models(Settings().models_config)
    servers = load_servers(Settings().mcp_servers_config)

    assert set(taxonomy.domains) == set(get_args(Domain))
    assert taxonomy.unknown_topics(["devops/ci-cd", "devops/", "sre/oncall"]) == [
        "devops/",
        "sre/oncall",
    ]
    assert any(model.supports_tools and model.min_role == "viewer" for model in models.values())
    assert servers["github"].url == "http://localhost:8082/mcp"  # GITHUB_MCP_URL unset


def test_a_taxonomy_without_every_domain_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.yaml"
    path.write_text("version: 1\ndomains:\n  db: {description: Databases}\n")

    with pytest.raises(ValidationError, match="missing domains"):
        load_taxonomy(str(path))


def test_models_and_tools_are_listed(client: TestClient) -> None:
    models = client.get("/v1/models").json()
    tools = client.get("/v1/tools").json()

    github = load_servers(Settings().mcp_servers_config)["github"]
    by_name = {t["name"]: t for t in tools}

    assert [m["id"] for m in models] == list(load_models(Settings().models_config))
    assert set(models[0]) == {"id", "label", "supports_tools", "tier", "min_role"}
    assert [t["name"] for t in tools] == sorted(by_name)
    assert [
        (t["name"], t["kind"], t["risk"], t["min_role"]) for t in tools if t["server"] == "kb"
    ] == [
        ("kb.get_document", "read", "low", "viewer"),
        ("kb.ingest_url", "write", "medium", "editor"),
        ("kb.list_sources", "read", "low", "viewer"),
        ("kb.search_knowledge_base", "read", "low", "viewer"),
    ]
    assert set(tools[0]) == {
        "name",
        "description",
        "kind",
        "risk",
        "min_role",
        "server",
        "domains",
        "available",
    }
    # Without GITHUB_PAT_READ, the sandbox PAT and WEB_FETCH_ALLOWED_HOSTS: listed, unavailable.
    assert {n for n, t in by_name.items() if t["server"] == "github"} == {
        f"github.{name}" for name in github.allow
    }
    assert by_name["github.actions_list"]["domains"] == ["devops", "dev"]
    sandbox = by_name["github_sandbox.create_issue"]
    assert (sandbox["kind"], sandbox["min_role"], sandbox["server"]) == ("write", "editor", None)
    web = by_name["web.fetch"]
    assert (web["kind"], web["min_role"], web["server"]) == ("read", "editor", None)
    assert [n for n, t in by_name.items() if not t["available"]] == [
        n for n in by_name if n.startswith("github") or n == "web.fetch"
    ]


def agent_body(**fields: Any) -> dict[str, Any]:
    message = {"role": "user", "parts": [{"type": "text", "text": "Q"}]}
    return {
        "conversation_id": "00000000-0000-0000-0000-000000000001",
        "messages": [message],
        **fields,
    }


@pytest.mark.parametrize(
    ("model", "status"),
    [
        ("openai/gpt-6-luna", 200),
        ("anthropic/claude-haiku-5.5", 422),  # editor+, the token is a viewer's
        ("someone/expensive-model", 422),
    ],
    ids=["viewer model", "above the role", "not in the registry"],
)
def test_agent_accepts_only_registry_models_of_the_role(
    client: TestClient, model: str, status: int
) -> None:
    assert client.post("/v1/agent", json=agent_body(model=model)).status_code == status


def fake_github() -> MCPServer:
    """External MCP server stand-in: read-only tools, one that writes, one that fails."""
    server = MCPServer("fake-github", cache_hints={"tools/list": CacheHint(ttl_ms=60_000)})
    read_only = ToolAnnotations(read_only_hint=True)

    @server.tool(annotations=read_only)
    def actions_list(owner: str, repo: str) -> str:  # pyright: ignore[reportUnusedFunction]
        """Workflow runs of a repository."""
        return f"runs of {owner}/{repo}: #42 failed"

    @server.tool(annotations=read_only)
    def list_tags(owner: str, repo: str) -> str:  # pyright: ignore[reportUnusedFunction]
        return "v1"

    @server.tool()
    def create_branch(branch: str) -> str:  # pyright: ignore[reportUnusedFunction]
        return f"created {branch}"

    @server.tool(annotations=read_only)
    def issue_read(number: int) -> str:  # pyright: ignore[reportUnusedFunction]
        raise ToolError("rate limited")

    return server


def external(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None = "pat",  # noqa: S107 - a fake
) -> tuple[McpServers, MCPServer, list[str]]:
    """The manager for one fake server; returns the MCP methods the server received."""
    if token:
        monkeypatch.setenv("TEST_PAT", token)
    config = ServerConfig(
        url="http://localhost:8082/mcp",
        bearer_env="TEST_PAT",
        allow=["actions_list", "create_branch", "issue_read", "renamed_tool"],
        domains=["devops"],
    )
    server = fake_github()
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    methods: list[str] = []

    async def recording(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] == "POST":
            methods.append(dict(scope["headers"]).get(b"mcp-method", b"").decode())
        await app(scope, receive, send)

    servers = McpServers({"github": config})
    servers.clients["github"].transport = httpx2.ASGITransport(app=recording)
    return servers, server, methods


def serving[T](server: MCPServer, use: Callable[[], Awaitable[T]]) -> T:
    async def run() -> T:
        async with server.session_manager.run():
            return await use()

    return asyncio.run(run())


def test_external_tools_are_allow_listed_read_only_and_namespaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers, server, methods = external(monkeypatch)

    async def use() -> tuple[list[ToolSpec[Any]], list[ToolOutput | str]]:
        tools = {tool.name: tool for tool in await servers.tools()}
        await servers.tools()  # the list is cached
        outputs: list[ToolOutput | str] = []
        for name, args in [("actions_list", {"owner": "o", "repo": "r"}), ("issue_read", {})]:
            try:
                outputs.append(await tools[f"github.{name}"].run(JsonArgs({"number": 1} | args)))
            except RuntimeError as error:
                outputs.append(str(error))
        return list(tools.values()), outputs

    tools, outputs = serving(server, use)

    available = {tool.name: tool.available for tool in tools}
    assert available == {
        "github.actions_list": True,
        "github.create_branch": False,  # not read-only
        "github.issue_read": True,
        "github.renamed_tool": False,  # not listed
    }
    runs = tools[0]
    assert (runs.server, runs.domains, runs.service_identity) == ("github", ("devops",), "TEST_PAT")
    assert runs.kind == "read"
    assert runs.definition()["function"]["name"] == "github_actions_list"
    assert runs.parameters and set(runs.parameters["properties"]) == {"owner", "repo"}
    assert outputs[0] == ToolOutput("runs of o/r: #42 failed", "23 chars")
    assert "rate limited" in str(outputs[1])
    assert methods.count("tools/list") == 1


@pytest.mark.parametrize("token", [None, "pat"], ids=["no credential", "server down"])
def test_an_unreachable_server_leaves_its_tools_unavailable(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    servers, _, methods = external(monkeypatch, token)
    servers.clients["github"].transport = None  # nothing listens on :8082 in tests
    monkeypatch.setattr(catalog, "LIST_TIMEOUT_S", 1)

    tools = asyncio.run(servers.tools())

    assert [tool.name for tool in tools if tool.available] == []
    assert len(tools) == 4
    assert methods == []


def test_on_a_name_clash_the_earlier_tool_group_wins() -> None:
    async def run(_: JsonArgs) -> ToolOutput:
        return ToolOutput("", "")

    def spec(name: str) -> ToolSpec[Any]:
        return ToolSpec(name=name, description=name, args=JsonArgs, run=run)

    native, clash, other = (
        spec("github_sandbox.create_issue"),
        spec("github.sandbox_create_issue"),
        spec("github.list_issues"),
    )

    assert registry([native], [clash, other]) == [native, other]


def test_server_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="transport"):
        ServerConfig.model_validate(
            {"url": "u", "bearer_env": "T", "allow": [], "transport": "stdio"}
        )
