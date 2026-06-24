"""Create run/serve engines from presets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flashcli_bundle.infer.bundle.resolve import load_preset_bundle
from flashcli_bundle.infer.engines.loader import load_run_engine, load_serve_engine
from flashcli_bundle.infer.engines.entry_invoke import entry_mode_for_manifest
from flashcli_bundle.infer.errors import BundleNotReadyError
from flashcli_bundle.manifest import EntryMode
from flashcli_bundle.preset import Preset


__all__ = [
    "BundleNotReadyError",
    "create_run_engine",
    "create_serve_engine",
    "entry_mode_for_preset",
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


def entry_mode_for_preset(
    preset: Preset,
    *,
    capability: str,
    bundle_path: Path | None = None,
) -> EntryMode:
    if preset.engine != "model_bundle":
        raise ValueError(f"Preset {preset.name!r} is not a model_bundle preset")
    bundle = load_preset_bundle(preset, bundle_override=bundle_path)
    return entry_mode_for_manifest(bundle, capability=capability)
