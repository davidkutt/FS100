import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from mcp import types
from pydantic import BaseModel, ConfigDict, model_validator

from ai_service.knowledge_base import Domain
from ai_service.mcp_client import McpClient
from ai_service.tools import JsonArgs, Role, ToolOutput, ToolSpec

LIST_TIMEOUT_S = 5  # a server that hangs must not stall every turn
_ENV = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")  # ${VAR} and ${VAR:-default}, as in Compose
logger = logging.getLogger(__name__)


class ModelInfo(BaseModel):
    """One `config/models.yaml` entry (D40); `id` is the model id at LLM_BASE_URL."""

    id: str
    label: str
    supports_tools: bool
    tier: Literal["low", "medium", "high"]
    min_role: Role


class DomainInfo(BaseModel):
    description: str
    topics: dict[str, str] = {}  # topic → description; the id is `domain/topic`


class Taxonomy(BaseModel):
    """`config/taxonomy.yaml` (D48)."""

    version: int
    domains: dict[Domain, DomainInfo]

    @model_validator(mode="after")
    def every_domain(self) -> "Taxonomy":
        if missing := set(get_args(Domain)) - set(self.domains):
            raise ValueError(f"missing domains: {sorted(missing)}")
        return self

    def topics(self) -> dict[str, str]:
        """`domain/topic` → description."""
        return {
            f"{domain}/{topic}": description
            for domain, info in self.domains.items()
            for topic, description in info.topics.items()
        }

    def unknown_topics(self, topics: list[str]) -> list[str]:
        return [topic for topic in topics if topic not in self.topics()]


class ServerConfig(BaseModel):
    """One `config/mcp_servers.yaml` entry (D38)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    bearer_env: str  # the variable holding its credential; also the audit's service identity
    allow: list[str]  # default-deny: only these tools reach the model
    domains: list[Domain] = []  # the routes that offer its tools; [] = every route
    min_role: Role = "viewer"
    timeout_s: float = 20


class McpServers:
    """External MCP servers as namespaced read tools (`github.actions_list`). A tool the server
    does not list (down, renamed) or does not mark read-only stays in the catalog, unavailable."""

    def __init__(self, servers: dict[str, ServerConfig]) -> None:
        self.clients = {
            name: McpClient(config.url, config.timeout_s) for name, config in servers.items()
        }
        self._servers = servers

    async def tools(self) -> list[ToolSpec[Any]]:
        listed = await asyncio.gather(*(self._tools(name) for name in self._servers))
        return [tool for tools in listed for tool in tools]

    async def _tools(self, server: str) -> list[ToolSpec[Any]]:
        config, client = self._servers[server], self.clients[server]
        listed: dict[str, types.Tool] = {}
        if token := os.environ.get(config.bearer_env):
            try:
                async with asyncio.timeout(LIST_TIMEOUT_S):
                    listed = {tool.name: tool for tool in await client.list_tools(token)}
            except Exception as error:
                logger.warning("MCP server %s unavailable: %r", server, error)
        return [self._spec(server, name, listed.get(name)) for name in config.allow]

    def _spec(self, server: str, name: str, tool: types.Tool | None) -> ToolSpec[Any]:
        config, client = self._servers[server], self.clients[server]
        read_only = bool(tool and tool.annotations and tool.annotations.read_only_hint)
        if tool and not read_only:
            logger.warning("%s.%s is not read-only and is not offered", server, name)

        async def run(args: JsonArgs) -> ToolOutput:
            result = await client.call(os.environ.get(config.bearer_env, ""), name, args.root)
            text = "\n".join(c.text for c in result.content if c.type == "text")
            if result.is_error:
                raise RuntimeError(text or "the server reported an error")
            content = text or json.dumps(result.structured_content, ensure_ascii=False)
            return ToolOutput(content, f"{len(content):,} chars")

        return ToolSpec(
            name=f"{server}.{name}",
            description=(tool and tool.description) or "",
            args=JsonArgs,
            run=run,
            min_role=config.min_role,
            timeout_s=config.timeout_s,
            parameters=tool.input_schema if tool else None,
            server=server,
            domains=tuple(config.domains),
            service_identity=config.bearer_env,
            available=read_only,
        )


def _read(path: str) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_models(path: str) -> dict[str, ModelInfo]:
    entries = [ModelInfo.model_validate(entry) for entry in _read(path)["models"]]
    return {entry.id: entry for entry in entries}


def load_taxonomy(path: str) -> Taxonomy:
    return Taxonomy.model_validate(_read(path))


def load_servers(path: str) -> dict[str, ServerConfig]:
    """Environment references are resolved here, so Mode B can point a URL at its container."""
    text = _ENV.sub(lambda m: os.environ.get(m[1], m[2] or ""), Path(path).read_text("utf-8"))
    config: Any = yaml.safe_load(text) or {}
    servers: dict[str, Any] = config.get("servers") or {}
    return {name: ServerConfig.model_validate(entry) for name, entry in servers.items()}
