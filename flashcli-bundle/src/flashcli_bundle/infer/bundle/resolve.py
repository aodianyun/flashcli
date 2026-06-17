"""Resolve model bundle path from preset ref and CLI overrides."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli_bundle.catalog import BundleCatalogError, repo_url_for_preset
from flashcli_bundle.infer.bundle.activate import activate_bundle
from flashcli_bundle.infer.errors import BundleNotReadyError
from flashcli_bundle.manifest_ext import (
    BundleManifest,
    load_bundle_manifest,
    resolve_bundle_env_key,
    validate_bundle_layout,
)
from flashcli_bundle.preset import Preset
from flashcli_bundle.resolve import load_preset_bundle, resolve_bundle_root

__all__ = [
    "activate_for_preset",
    "load_preset_bundle",
    "resolve_bundle_root",
]


def activate_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    auto_install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> BundleManifest:
    try:
        bundle = load_preset_bundle(preset, bundle_override=bundle_path)
    except (FileNotFoundError, BundleCatalogError) as exc:
        raise BundleNotReadyError(str(exc)) from exc

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
