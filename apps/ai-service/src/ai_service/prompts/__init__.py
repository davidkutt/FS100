"""Prompts are reviewed files with front matter `id` and `version` (D46, ADR-0013)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    text: str
    hash: str  # of the text, so an edit without a version bump still shows

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


def load(name: str) -> Prompt:
    _, front, text = (Path(__file__).parent / f"{name}.md").read_text("utf-8").split("---\n", 2)
    meta = yaml.safe_load(front)
    text = text.strip()
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    return Prompt(meta["id"], int(meta["version"]), text, digest)
