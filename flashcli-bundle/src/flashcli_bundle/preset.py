"""Catalog preset view exposed to bundle entry modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Preset:
    """Minimal preset handle passed to ``RunEngine.load`` / ``ServeEngine.load``."""

    name: str
    raw: dict[str, Any] = field(default_factory=dict)
    cache_key: str = ""

    @property
    def bundle_variant(self) -> str | None:
        for key in ("bundle_variant", "variant", "model_variant", "model"):
            value = self.raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @property
    def engine(self) -> str:
        return str(self.raw.get("engine", "model_bundle"))

    @property
    def description(self) -> str:
        explicit = str(self.raw.get("description", "")).strip()
        if explicit:
            return explicit
        bundle = self.raw.get("bundle")
        if not isinstance(bundle, dict):
            return self.name
        repo = str(bundle.get("repo", "")).strip()
        if repo:
            label = repo if len(repo) <= 72 else repo[:69] + "..."
            return f"bundle:repo={label}"
        return self.name
