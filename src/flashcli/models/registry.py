"""Load model presets from models.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from flashcli import config


@dataclass
class Preset:
    name: str
    raw: dict[str, Any]

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
        path = str(bundle.get("path", "")).strip()
        if path:
            return f"bundle:path={path}"
        zip_src = str(bundle.get("zip", "")).strip()
        if zip_src:
            label = zip_src if len(zip_src) <= 72 else zip_src[:69] + "..."
            return f"bundle:zip={label}"
        git = bundle.get("git")
        if isinstance(git, dict):
            repo = str(git.get("repo", "")).strip()
            if repo:
                ref = str(git.get("ref", "main")).strip() or "main"
                return f"bundle:git={repo}@{ref}"
        return self.name


class PresetRegistry:
    def __init__(self, manifest_path: Path | None = None) -> None:
        self.manifest_path = manifest_path or config.MODELS_YAML

    def load(self) -> dict[str, Preset]:
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"models.yaml not found: {self.manifest_path}")
        data = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        models = data.get("models", {})
        return {name: Preset(name=name, raw=cfg) for name, cfg in models.items()}

    def get(self, name: str) -> Preset:
        presets = self.load()
        if name not in presets:
            known = ", ".join(sorted(presets))
            raise KeyError(f"Unknown preset {name!r}. Known: {known}")
        preset = presets[name]
        if preset.engine != "model_bundle":
            raise ValueError(
                f"Preset {name!r} uses unsupported engine {preset.engine!r}; "
                "only model_bundle is supported."
            )
        return preset

    def list_names(self) -> list[str]:
        return sorted(self.load().keys())
