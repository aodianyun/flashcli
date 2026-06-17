"""Host-side bundle help (manifest-only; no re-exec to infer)."""

from __future__ import annotations

from pathlib import Path

from flashcli_bundle.help_text import format_run_help, format_serve_help
from flashcli_bundle.manifest_resolve import resolve_manifest_for_preset
from flashcli_bundle.options import (
    bundle_run_options_for_help,
    bundle_serve_options_for_help,
    resolve_options_variant,
)
from flashcli.models.registry import Preset


def format_command_help(
    preset: Preset,
    bundle_path: Path | None,
    *,
    command: str,
) -> str:
    """Build run/serve help from manifest only (no full bundle sync)."""
    manifest = resolve_manifest_for_preset(preset, bundle_path=bundle_path)
    variant_key = resolve_options_variant(manifest, preset)
    if command == "run":
        specs = bundle_run_options_for_help(manifest, variant=variant_key)
        return format_run_help(preset, manifest, specs)
    if command == "serve":
        specs = bundle_serve_options_for_help(manifest, variant=variant_key)
        return format_serve_help(preset, manifest, specs)
    raise ValueError(f"unknown command: {command!r}")
