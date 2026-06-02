"""Create run/serve engines from presets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flashcli.bundle.activate import activate_bundle
from flashcli.bundle.catalog import BundleCatalogError
from flashcli.bundle.manifest import BundleManifest, validate_bundle_layout
from flashcli.bundle.resolve import load_preset_bundle
from flashcli.engines.loader import load_run_engine, load_serve_engine
from flashcli.models.registry import Preset


class BundleNotReadyError(RuntimeError):
    exit_code = 2


def activate_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
    auto_install_python: bool = True,
    quiet: bool = False,
    force_python: bool = False,
) -> BundleManifest:
    """Activate the preset's model bundle runtime."""
    if preset.engine != "model_bundle":
        raise ValueError(
            f"Preset {preset.name!r} uses engine {preset.engine!r}; "
            "only model_bundle is supported."
        )

    try:
        bundle = load_preset_bundle(
            preset,
            bundle_override=bundle_path,
            bundle_ref=bundle_ref or bundle_version,
            checkpoint=checkpoint,
            fetch_git=bundle_path is None,
            quiet=quiet,
        )
    except BundleCatalogError as exc:
        raise BundleNotReadyError(str(exc)) from exc
    errors = validate_bundle_layout(bundle)
    if errors:
        raise BundleNotReadyError(
            "Invalid model bundle:\n  " + "\n  ".join(errors)
        )
    activate_bundle(
        bundle,
        install_python=auto_install_python,
        quiet=quiet,
        force_python=force_python,
    )
    return bundle


def create_run_engine(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
) -> Any:
    if preset.engine != "model_bundle":
        raise ValueError(f"Preset {preset.name!r} is not a model_bundle preset")
    bundle = load_preset_bundle(
        preset,
        bundle_override=bundle_path,
        bundle_ref=bundle_ref or bundle_version,
        checkpoint=checkpoint,
        fetch_git=bundle_path is None,
    )
    if bundle.entry_run is None:
        raise ValueError(f"Preset {preset.name!r} has no entry.run")
    return load_run_engine(bundle.entry_run)


def create_serve_engine(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
) -> Any:
    if preset.engine != "model_bundle":
        raise ValueError(f"Preset {preset.name!r} is not a model_bundle preset")
    bundle = load_preset_bundle(
        preset,
        bundle_override=bundle_path,
        bundle_ref=bundle_ref or bundle_version,
        checkpoint=checkpoint,
        fetch_git=bundle_path is None,
    )
    if bundle.entry_serve is None:
        raise ValueError(f"Preset {preset.name!r} has no entry.serve")
    return load_serve_engine(bundle.entry_serve)
