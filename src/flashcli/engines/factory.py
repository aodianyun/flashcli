"""Create run/serve engines from presets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flashcli.bundle.resolve import activate_for_preset, load_preset_bundle
from flashcli.engines.loader import load_run_engine, load_serve_engine
from flashcli.models.registry import Preset


class BundleNotReadyError(RuntimeError):
    exit_code = 2


__all__ = [
    "BundleNotReadyError",
    "activate_for_preset",
    "create_run_engine",
    "create_serve_engine",
]


def create_run_engine(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> Any:
    if preset.engine != "model_bundle":
        raise ValueError(f"Preset {preset.name!r} is not a model_bundle preset")
    bundle = load_preset_bundle(preset, bundle_override=bundle_path)
    if bundle.entry_run is None:
        raise ValueError(f"Preset {preset.name!r} has no entry.run")
    return load_run_engine(bundle.entry_run)


def create_serve_engine(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> Any:
    if preset.engine != "model_bundle":
        raise ValueError(f"Preset {preset.name!r} is not a model_bundle preset")
    bundle = load_preset_bundle(preset, bundle_override=bundle_path)
    if bundle.entry_serve is None:
        raise ValueError(f"Preset {preset.name!r} has no entry.serve")
    return load_serve_engine(bundle.entry_serve)
