"""Remove all local cache artifacts for a preset ref (host CLI only)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from flashcli_bundle import paths as config
from flashcli_bundle.manifest import BundleManifest, load_bundle_manifest
from flashcli_bundle.marker import read_preset_marker, runtime_dir
from flashcli_bundle.preset import Preset
from flashcli_bundle.preset_ref import preset_cache_key
from flashcli_bundle.weights import extra_weights_spec


def _rmtree(path: Path) -> bool:
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def _extra_weight_dirs(
    bundle: BundleManifest,
    *,
    variant: str | None,
) -> list[Path]:
    dirs: list[Path] = []
    extra = extra_weights_spec(bundle, variant=variant)
    for key, spec in extra.items():
        if not isinstance(spec, dict):
            continue
        rel = str(spec.get("relative_dir", "")).strip()
        if rel:
            dirs.append((bundle.bundle_root / rel).resolve())
            continue
        cache_name = str(spec.get("cache_name", key)).strip()
        if cache_name:
            dirs.append(config.MODELS_DIR / cache_name)
    return dirs


def _flashhub_index_paths(marker: dict[str, Any]) -> list[Path]:
    repo = str(marker.get("repo", "")).strip()
    if not repo:
        return []
    key = hashlib.sha256(repo.encode()).hexdigest()[:16]
    path = config.CACHE_DIR / "repo-index" / f"{key}.json"
    return [path] if path.is_file() else []


def clean_preset_cache(
    preset: Preset,
    *,
    include_flashhub_cache: bool = False,
) -> list[str]:
    """Delete runtime, weights, preset marker, and manifest extra_weights for *preset*."""
    removed: list[str] = []
    marker = read_preset_marker(preset) or {}
    cache_key = preset_cache_key(preset)
    variant = preset.bundle_variant

    manifest: BundleManifest | None = None
    bundle_root = str(marker.get("bundle_root", "")).strip()
    if bundle_root:
        root = Path(bundle_root).expanduser()
        if root.is_dir() and (root / "flashcli-bundle.json").is_file():
            try:
                manifest = load_bundle_manifest(root)
            except (FileNotFoundError, ValueError, OSError):
                manifest = None

    if manifest is not None:
        for path in _extra_weight_dirs(manifest, variant=variant):
            if _rmtree(path):
                removed.append(str(path))

    weights_dir = config.MODELS_DIR / cache_key
    if _rmtree(weights_dir):
        removed.append(str(weights_dir))

    marker_dir = config.BUNDLES_DIR / cache_key
    if _rmtree(marker_dir):
        removed.append(str(marker_dir))

    runtime_id = str(marker.get("runtime_id", "")).strip()
    if runtime_id:
        rt = runtime_dir(runtime_id)
        if _rmtree(rt):
            removed.append(str(rt))

    if include_flashhub_cache:
        for path in _flashhub_index_paths(marker):
            path.unlink(missing_ok=True)
            removed.append(str(path))

    return removed


def clean_all_cached(
    *,
    include_flashhub_cache: bool = False,
) -> list[str]:
    """Remove all cached runtimes, weights, and preset markers."""
    removed: list[str] = []
    for root in (config.RUNTIMES_DIR, config.MODELS_DIR, config.BUNDLES_DIR):
        if _rmtree(root):
            removed.append(str(root))
    if include_flashhub_cache:
        index_dir = config.CACHE_DIR / "repo-index"
        if _rmtree(index_dir):
            removed.append(str(index_dir))
    return removed
