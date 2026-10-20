from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, model_validator

from ai_service.knowledge_base import Domain
from ai_service.tools import Role


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

    def unknown_topics(self, topics: list[str]) -> list[str]:
        known = {
            f"{domain}/{topic}" for domain, info in self.domains.items() for topic in info.topics
        }
        return [topic for topic in topics if topic not in known]


def _read(path: str) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_models(path: str) -> dict[str, ModelInfo]:
    entries = [ModelInfo.model_validate(entry) for entry in _read(path)["models"]]
    return {entry.id: entry for entry in entries}


def load_taxonomy(path: str) -> Taxonomy:
    return Taxonomy.model_validate(_read(path))
