"""Help text for ``flashcli run|serve`` (protocol layer; no infer import)."""

from __future__ import annotations

import argparse

from flashcli_bundle.manifest import BundleManifest, EntryMode
from flashcli_bundle.options import OptionSpec
from flashcli_bundle.preset import Preset

COMMON_RUN_OPTIONS_HELP: list[tuple[str, str]] = [
    (
        "REF",
        "FlashHub ref namespace/bundle:version[@variant], or local path PATH[@variant].",
    ),
    ("--checkpoint PATH", "Override checkpoint directory (skip cache/download)."),
    (
        "--mtp-checkpoint PATH",
        "Override MTP weights dir (sets FLASHRT_QWEN36_MTP_CKPT_DIR).",
    ),
    ("--benchmark N", "Timed predict iterations after the first run."),
    (
        "--warmup N",
        "Extra predict iterations before --benchmark (orchestration warmup).",
    ),
    ("--no-auto-install", "Do not auto-install bundle Python deps."),
    ("--quiet, -q", "Less output."),
]

COMMON_SERVE_OPTIONS_HELP: list[tuple[str, str]] = [
    (
        "REF",
        "FlashHub ref namespace/bundle:version[@variant], or local path PATH[@variant].",
    ),
    ("--checkpoint PATH", "Override checkpoint directory."),
    ("--mtp-checkpoint PATH", "Override MTP weights dir."),
    ("--port PORT", "HTTP listen port (default: 8000)."),
    ("--host HOST", "HTTP listen address (default: 0.0.0.0)."),
    ("--no-auto-install", "Do not auto-install bundle Python deps."),
    ("--quiet, -q", "Less output."),
]

SCRIPT_RUN_COMMON_OPTIONS_HELP: list[tuple[str, str]] = [
    (
        "REF",
        "FlashHub ref namespace/bundle:version[@variant], or local path PATH[@variant].",
    ),
    ("--checkpoint PATH", "Override checkpoint directory (skip cache/download)."),
]

SCRIPT_SERVE_COMMON_OPTIONS_HELP: list[tuple[str, str]] = [
    (
        "REF",
        "FlashHub ref namespace/bundle:version[@variant], or local path PATH[@variant].",
    ),
    ("--checkpoint PATH", "Override checkpoint directory (skip cache/download)."),
]

SCRIPT_MODE_NOTE = (
    "Script mode: bundle options below are documentation only; "
    "all flags after REF are passed through to the entry script."
)


def _format_options_help(
    title: str,
    specs: list[OptionSpec],
    *,
    default_phase: str,
    documentation_only: bool = False,
) -> list[str]:
    lines = [title]
    if documentation_only:
        lines[-1] = f"{title} (documentation; parsed by bundle script in script mode):"
    if specs:
        for spec in sorted(specs, key=lambda s: s.flag):
            default = ""
            if spec.default is not argparse.SUPPRESS and spec.default is not None:
                default = f" (default: {spec.default})"
            variant = f" [{spec.variant}]" if spec.variant else ""
            phase = f" [{spec.phase}]" if spec.phase != default_phase else ""
            lines.append(f"  --{spec.flag:<22}{spec.help}{default}{phase}{variant}")
    else:
        lines.append("  (none declared in manifest)")
    return lines


def format_run_help(
    preset: Preset,
    manifest: BundleManifest,
    specs: list[OptionSpec],
    *,
    entry_mode: EntryMode = "engine",
) -> str:
    if entry_mode == "script":
        usage = f"Usage: flashcli run {preset.name} [OPTIONS...]"
        common = SCRIPT_RUN_COMMON_OPTIONS_HELP
        doc_only = True
    else:
        usage = f"Usage: flashcli run {preset.name} [COMMON OPTIONS] [BUNDLE OPTIONS]"
        common = COMMON_RUN_OPTIONS_HELP
        doc_only = False
    lines = [
        usage,
        "",
        manifest.description or preset.description or "",
        "",
        "Common options (flashcli):",
    ]
    for flag, text in common:
        lines.append(f"  {flag:<24}  {text}")
    lines.append("")
    lines.extend(
        _format_options_help(
            "Bundle run options:",
            specs,
            default_phase="predict",
            documentation_only=doc_only,
        )
    )
    if entry_mode == "script":
        lines.append("")
        lines.append(SCRIPT_MODE_NOTE)
    lines.append("")
    lines.append("Use flashcli models envs to check runtime GPU/CUDA support.")
    return "\n".join(lines)


def format_serve_help(
    preset: Preset,
    manifest: BundleManifest,
    specs: list[OptionSpec],
    *,
    entry_mode: EntryMode = "engine",
) -> str:
    if entry_mode == "script":
        usage = f"Usage: flashcli serve {preset.name} [OPTIONS...]"
        common = SCRIPT_SERVE_COMMON_OPTIONS_HELP
        doc_only = True
    else:
        usage = f"Usage: flashcli serve {preset.name} [COMMON OPTIONS] [BUNDLE OPTIONS]"
        common = COMMON_SERVE_OPTIONS_HELP
        doc_only = False
    lines = [
        usage,
        "",
        manifest.description or preset.description or "",
        "",
        "Common options (flashcli):",
    ]
    for flag, text in common:
        lines.append(f"  {flag:<24}  {text}")
    lines.append("")
    lines.extend(
        _format_options_help(
            "Bundle serve options:",
            specs,
            default_phase="load",
            documentation_only=doc_only,
        )
    )
    if entry_mode == "script":
        lines.append("")
        lines.append(SCRIPT_MODE_NOTE)
    lines.append("")
    lines.append("Use flashcli models envs to check runtime GPU/CUDA support.")
    return "\n".join(lines)
