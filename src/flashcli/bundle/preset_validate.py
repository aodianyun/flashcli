"""Validate preset ref against manifest before artifact download."""

from __future__ import annotations

import tempfile
from pathlib import Path

from flashcli.bundle.catalog import repo_url_for_preset
from flashcli.bundle.flashhub import download_manifest_from_repo
from flashcli.bundle.layout import is_bundle_root
from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, load_bundle_manifest_data
from flashcli.bundle.marker import read_preset_marker
from flashcli.bundle.preflight import BundleEnvironmentError, run_preflight
from flashcli.models.preset_ref import preset_cache_key
from flashcli.models.registry import Preset


def fetch_manifest_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    quiet: bool = False,
) -> BundleManifest:
    """Load manifest: local bundle, cached runtime, or manifest-only from FlashHub."""
    if bundle_path is not None:
        root = bundle_path.expanduser().resolve()
        if not is_bundle_root(root):
            raise FileNotFoundError(f"Not a bundle root: {root}")
        return load_bundle_manifest(root)

    repo = repo_url_for_preset(preset)
    marker = read_preset_marker(preset) or {}
    marker_repo = str(marker.get("repo", "")).strip()
    cached_root = str(marker.get("bundle_root", "")).strip()
    if cached_root and (not marker_repo or marker_repo == repo):
        root = Path(cached_root).expanduser().resolve()
        if is_bundle_root(root):
            try:
                return load_bundle_manifest(root)
            except ValueError:
                pass

    key = preset_cache_key(preset)
    tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{key}.json"
    data = download_manifest_from_repo(repo, tmp, quiet=quiet)
    return load_bundle_manifest_data(data, bundle_root=Path("/tmp"))


def validate_preset_manifest(preset: Preset, manifest: BundleManifest) -> None:
    """Require explicit @variant for multi-variant bundles; preflight GPU/env."""
    from flashcli.bundle.variants import validate_required_variant

    validate_required_variant(preset, manifest)
    run_preflight(manifest)


def validate_preset_before_sync(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    quiet: bool = False,
) -> BundleManifest:
    """Fetch manifest (cache or manifest-only), validate variant + preflight."""
    try:
        manifest = fetch_manifest_for_preset(
            preset, bundle_path=bundle_path, quiet=quiet
        )
        validate_preset_manifest(preset, manifest)
    except BundleEnvironmentError:
        raise
    except ValueError as exc:
        raise BundleEnvironmentError(str(exc)) from exc
    return manifest
