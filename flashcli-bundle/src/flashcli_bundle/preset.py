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
