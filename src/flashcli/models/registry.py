"""Preset handle for bundle runtimes (resolved from FlashHub refs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flashcli_bundle.preset import Preset as BundlePreset


@dataclass
class Preset(BundlePreset):
    """Host preset; extends :mod:`flashcli_bundle.preset` with cache metadata."""

    cache_key: str = ""

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
