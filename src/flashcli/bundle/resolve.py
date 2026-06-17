"""Resolve model bundle path from preset ref and CLI overrides."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli.bundle.activate import activate_bundle
from flashcli.bundle.catalog import BundleCatalogError, repo_url_for_preset
from flashcli.bundle.layout import is_bundle_root
from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, validate_bundle_layout
from flashcli.bundle.marker import read_preset_marker
from flashcli.models.registry import Preset


def resolve_bundle_root(
    preset: Preset,
    *,
    bundle_override: Path | None = None,
) -> Path:
    """Return absolute bundle root (requires prior runtime prepare + reexec)."""
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

    repo_url_for_preset(preset)  # validate ref
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


def activate_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    auto_install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> BundleManifest:
    from flashcli.engines.factory import BundleNotReadyError

    try:
        bundle = load_preset_bundle(preset, bundle_override=bundle_path)
    except (FileNotFoundError, BundleCatalogError) as exc:
        raise BundleNotReadyError(str(exc)) from exc

    from flashcli.bundle.manifest import resolve_bundle_env_key

    try:
        env_key = resolve_bundle_env_key(bundle)
    except RuntimeError as exc:
        raise BundleNotReadyError(str(exc)) from exc

    errors = validate_bundle_layout(bundle, env_key=env_key)
    if errors:
        raise BundleNotReadyError(
            "Invalid model bundle:\n  " + "\n  ".join(errors)
        )

    runtime_id = os.environ.get("FLASHCLI_RUNTIME_ID")
    activate_bundle(
        bundle,
        runtime_id=runtime_id,
        install_python=auto_install_python,
        quiet=quiet,
        force_python=force_python,
    )
    return bundle
