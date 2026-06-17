"""Host-side argv helpers for ``run`` / ``serve`` (ref + weight pull flags only)."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from flashcli_bundle.options import BundleOptionsError
from flashcli.models.preset_ref import resolve_run_target
from flashcli.models.registry import Preset


@dataclass
class HostRunFlags:
    quiet: bool = False
    no_auto_install: bool = False
    checkpoint: Path | None = None
    mtp_checkpoint: Path | None = None
    wants_help: bool = False


def resolve_run_from_argv(
    argv: list[str],
    *,
    command: str,
) -> tuple[Preset, Path | None]:
    """Parse ``run|serve`` argv into (preset, optional local bundle root)."""
    rest = list(argv)
    if rest and rest[0] == command:
        rest = rest[1:]
    if not rest:
        raise BundleOptionsError(
            f"Usage: flashcli {command} REF[@variant] [OPTIONS]\n"
            f"Try 'flashcli {command} --help' for bundle-specific options."
        )
    if rest[0] in ("-h", "--help") and len(rest) == 1:
        raise BundleOptionsError(
            f"Usage: flashcli {command} REF[@variant] [OPTIONS]\n"
            f"Try 'flashcli {command} <ref> --help' for bundle-specific options."
        )

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("ref", nargs="?")
    ns, _ = pre.parse_known_args(rest)
    positional = ns.ref
    if positional is None and rest and not rest[0].startswith("-"):
        positional = rest[0]
    try:
        preset, bundle_path = resolve_run_target(positional)
    except ValueError as exc:
        raise BundleOptionsError(str(exc)) from exc
    if not isinstance(preset, Preset):
        preset = Preset(name=preset.name, raw=preset.raw, cache_key=preset.cache_key)
    return preset, bundle_path


def peel_host_run_flags(argv: list[str], *, command: str) -> HostRunFlags:
    """Extract host-only flags (weights, quiet) before re-exec to infer."""
    rest = list(argv)
    if rest and rest[0] == command:
        rest = rest[1:]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("ref", nargs="?")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--mtp-checkpoint", dest="mtp_checkpoint", type=Path)
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("--no-auto-install", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    ns, _ = parser.parse_known_args(rest)
    return HostRunFlags(
        quiet=ns.quiet,
        no_auto_install=ns.no_auto_install,
        checkpoint=ns.checkpoint,
        mtp_checkpoint=ns.mtp_checkpoint,
        wants_help=ns.help,
    )


def generic_run_usage(command: str) -> str:
    return (
        f"Usage: flashcli {command} REF[@variant] [OPTIONS]\n"
        "Bundle-specific options are shown after sync via:\n"
        f"  flashcli {command} <ref> --help"
    )
