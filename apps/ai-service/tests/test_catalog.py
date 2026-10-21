"""Model registry, tool catalog and taxonomy (D30, D40, D48)."""

from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_service.catalog import load_models, load_taxonomy
from ai_service.core.settings import Settings
from ai_service.knowledge_base import Domain


def test_committed_config_files_are_valid() -> None:
    taxonomy = load_taxonomy(Settings().taxonomy_config)
    models = load_models(Settings().models_config)

    assert set(taxonomy.domains) == set(get_args(Domain))
    assert taxonomy.unknown_topics(["devops/ci-cd", "devops/", "sre/oncall"]) == [
        "devops/",
        "sre/oncall",
    ]
    assert any(model.supports_tools and model.min_role == "viewer" for model in models.values())


def test_a_taxonomy_without_every_domain_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.yaml"
    path.write_text("version: 1\ndomains:\n  db: {description: Databases}\n")

    with pytest.raises(ValidationError, match="missing domains"):
        load_taxonomy(str(path))


def test_models_and_tools_are_listed(client: TestClient) -> None:
    models = client.get("/v1/models").json()
    tools = client.get("/v1/tools").json()

    assert [m["id"] for m in models] == list(load_models(Settings().models_config))
    assert set(models[0]) == {"id", "label", "supports_tools", "tier", "min_role"}
    assert [(t["name"], t["kind"], t["risk"], t["min_role"]) for t in tools] == [
        ("kb.get_document", "read", "low", "viewer"),
        ("kb.ingest_url", "write", "medium", "editor"),
        ("kb.list_sources", "read", "low", "viewer"),
        ("kb.search_knowledge_base", "read", "low", "viewer"),
    ]
    assert set(tools[0]) == {"name", "description", "kind", "risk", "min_role"}


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
