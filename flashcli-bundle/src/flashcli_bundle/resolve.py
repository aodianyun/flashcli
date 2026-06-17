"""Resolve model bundle path from preset ref and CLI overrides."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli_bundle.catalog import repo_url_for_preset
from flashcli_bundle.layout import is_bundle_root
from flashcli_bundle.manifest import BundleManifest, load_bundle_manifest
from flashcli_bundle.marker import read_preset_marker
from flashcli_bundle.preset import Preset


def resolve_bundle_root(
    preset: Preset,
    *,
    bundle_override: Path | None = None,
) -> Path:
    env_root = os.environ.get("FLASHCLI_BUNDLE_ROOT", "").strip()
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if is_bundle_root(root):
            return root
    if bundle_override is not None:
        root = bundle_override.expanduser().resolve()
        if not is_bundle_root(root):
            raise FileNotFoundError(f"Bundle directory not found: {root}")
        return root
    marker = read_preset_marker(preset)
    if marker:
        marker_root = str(marker.get("bundle_root", "")).strip()
        if marker_root:
            root = Path(marker_root).expanduser().resolve()
            if is_bundle_root(root):
                return root
    repo_url_for_preset(preset)
    if not env_root:
        raise FileNotFoundError(
            f"No bundle runtime for preset {preset.name!r}. "
            f"Run 'flashcli bundle sync {preset.name}' first."
        )
    raise FileNotFoundError(f"Invalid FLASHCLI_BUNDLE_ROOT: {env_root}")


def load_preset_bundle(
    preset: Preset,
    *,
    bundle_override: Path | None = None,
) -> BundleManifest:
    root = resolve_bundle_root(preset, bundle_override=bundle_override)
    return load_bundle_manifest(root)


__all__ = ["load_preset_bundle", "resolve_bundle_root"]
