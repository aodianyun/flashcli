"""Resolve ``flashcli-bundle.json`` for a preset (manifest-only; no full bundle sync)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from flashcli_bundle.catalog import raw_bundle_cfg, repo_url_for_preset
from flashcli_bundle.flashhub import download_manifest_from_repo
from flashcli_bundle.layout import is_bundle_root
from flashcli_bundle.manifest import (
    BundleManifest,
    load_bundle_manifest,
    load_bundle_manifest_data,
)
from flashcli_bundle.marker import read_preset_marker
from flashcli_bundle.preset import Preset
from flashcli_bundle.preset_ref import preset_cache_key


def _catalog_repo_url(cfg: dict[str, Any]) -> str:
    return str(cfg.get("repo", "")).strip()


def _try_load_bundle_manifest(root: Path) -> BundleManifest | None:
    if not is_bundle_root(root):
        return None
    try:
        return load_bundle_manifest(root)
    except ValueError:
        return None


def resolve_manifest_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> BundleManifest:
    """Load manifest from local bundle, cache marker, or FlashHub (manifest file only)."""
    env_root = os.environ.get("FLASHCLI_BUNDLE_ROOT", "").strip()
    if env_root:
        manifest = _try_load_bundle_manifest(Path(env_root).expanduser().resolve())
        if manifest is not None:
            return manifest

    if bundle_path is not None:
        root = bundle_path.expanduser().resolve()
        if is_bundle_root(root):
            return load_bundle_manifest(root)

    cfg = raw_bundle_cfg(preset)
    marker = read_preset_marker(preset) or {}
    catalog_repo = _catalog_repo_url(cfg)
    marker_repo = str(marker.get("repo", "")).strip()
    cached_root = str(marker.get("bundle_root", "")).strip()
    cache_repo_matches = not catalog_repo or not marker_repo or marker_repo == catalog_repo

    if cached_root and cache_repo_matches:
        manifest = _try_load_bundle_manifest(Path(cached_root).expanduser().resolve())
        if manifest is not None:
            return manifest

    repo = catalog_repo
    if not repo:
        if bundle_path is not None:
            raise FileNotFoundError(f"Bundle root not found: {bundle_path}")
        raise FileNotFoundError(
            f"Preset {preset.name!r} has no bundle.repo and no cached bundle"
        )

    key = preset_cache_key(preset)
    tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{key}.json"
    data = download_manifest_from_repo(repo_url_for_preset(preset), tmp, quiet=True)
    root = Path(cached_root) if cached_root else tmp.parent
    return load_bundle_manifest_data(data, bundle_root=root)
