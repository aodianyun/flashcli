"""CLI argv parsing for bundle-declared ``run_options`` / ``serve_options``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flashcli_bundle.help_text import format_run_help, format_serve_help
from flashcli_bundle.manifest_resolve import resolve_manifest_for_preset
from flashcli_bundle.options import (
    BundleOptionsError,
    OptionSpec,
    bundle_run_options,
    bundle_run_options_for_help,
    bundle_serve_options,
    bundle_serve_options_for_help,
    option_value,
    resolve_options_variant,
    run_option_defaults,
    serve_option_defaults,
    split_run_options,
    split_serve_options,
    validate_bundle_options,
)
from flashcli_bundle.preset import Preset

__all__ = [
    "BundleOptionsError",
    "OptionSpec",
    "RunInvocation",
    "ServeInvocation",
    "bundle_run_options",
    "bundle_run_options_for_help",
    "bundle_serve_options",
    "bundle_serve_options_for_help",
    "format_run_help",
    "format_serve_help",
    "option_value",
    "parse_run_argv",
    "parse_serve_argv",
    "resolve_manifest_for_preset",
    "resolve_run_from_argv",
    "resolve_options_variant",
    "run_option_defaults",
    "serve_option_defaults",
    "split_run_options",
    "split_serve_options",
    "validate_bundle_options",
]


@dataclass
class RunInvocation:
    preset: str
    help: bool = False
    bundle: Path | None = None
    checkpoint: Path | None = None
    mtp_checkpoint: Path | None = None
    benchmark: int = 0
    warmup: int = 0
    no_auto_install: bool = False
    quiet: bool = False
    bundle_options: dict[str, Any] | None = None
    option_specs: list[OptionSpec] | None = None


@dataclass
class ServeInvocation:
    preset: str
    help: bool = False
    bundle: Path | None = None
    checkpoint: Path | None = None
    mtp_checkpoint: Path | None = None
    port: int = 8000
    host: str = "0.0.0.0"
    no_auto_install: bool = False
    quiet: bool = False
    bundle_options: dict[str, Any] | None = None
    option_specs: list[OptionSpec] | None = None


def resolve_run_from_argv(
    argv: list[str],
    *,
    command: str,
) -> tuple[Preset, Path | None]:
    """Parse ``run|serve`` argv into (preset, optional local bundle root)."""
    from flashcli_bundle.preset_ref import resolve_run_target

    rest = list(argv)
    if rest and rest[0] == command:
        rest = rest[1:]
    if not rest:
        raise BundleOptionsError(
            f"Usage: flashcli {command} REF[@variant] [OPTIONS]\n"
            f"Try 'flashcli {command} --help' for bundle-specific options."
        )
    if rest[0] in ("-h", "--help"):
        raise BundleOptionsError(
            f"Usage: flashcli {command} REF[@variant] [OPTIONS]\n"
            f"Try 'flashcli {command} --help' for bundle-specific options."
        )

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("ref", nargs="?")
    ns, _ = pre.parse_known_args(rest)
    positional = ns.ref
    if positional is None and rest and not rest[0].startswith("-"):
        positional = rest[0]
    try:
        return resolve_run_target(positional)
    except ValueError as exc:
        raise BundleOptionsError(str(exc)) from exc


def _peek_command_argv(
    argv: list[str],
    *,
    default_preset: str,
    bundle_path: Path | None,
) -> tuple[str, Path | None, str | None]:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("ref", nargs="?")
    ns, _ = pre.parse_known_args(argv)
    preset_name = ns.ref or default_preset
    if ns.ref is None and argv and not argv[0].startswith("-"):
        preset_name = argv[0]
    return preset_name, bundle_path, None


def _add_spec_to_parser(parser: argparse.ArgumentParser, spec: OptionSpec) -> None:
    from flashcli_bundle.options import parse_bool_arg

    flag = f"--{spec.flag}"
    kwargs: dict[str, Any] = {"dest": spec.name, "help": spec.help}
    if spec.type == "boolean":
        kwargs["type"] = parse_bool_arg
        kwargs["nargs"] = "?"
        kwargs["const"] = True
        if spec.default is not argparse.SUPPRESS:
            kwargs["default"] = spec.default
        else:
            kwargs["default"] = argparse.SUPPRESS
    else:
        kwargs["type"] = spec.argparse_type()
        if spec.default is not argparse.SUPPRESS:
            kwargs["default"] = spec.default
        else:
            kwargs["default"] = argparse.SUPPRESS
    parser.add_argument(flag, **kwargs)


def _build_run_parser(preset_name: str, specs: list[OptionSpec]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("ref", nargs="?", default=preset_name)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--mtp-checkpoint", dest="mtp_checkpoint", type=Path)
    parser.add_argument("--benchmark", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--no-auto-install", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    for spec in specs:
        _add_spec_to_parser(parser, spec)
    return parser


def _build_serve_parser(preset_name: str, specs: list[OptionSpec]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("ref", nargs="?", default=preset_name)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--mtp-checkpoint", dest="mtp_checkpoint", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-auto-install", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    for spec in specs:
        _add_spec_to_parser(parser, spec)
    return parser


def _collect_bundle_options(ns: argparse.Namespace, specs: list[OptionSpec]) -> dict[str, Any]:
    bundle_options: dict[str, Any] = {}
    for spec in specs:
        if hasattr(ns, spec.name):
            value = getattr(ns, spec.name)
            if value is argparse.SUPPRESS:
                continue
            bundle_options[spec.name] = value
    return bundle_options


def parse_run_argv(
    argv: list[str] | None = None,
    *,
    preset: Preset,
    bundle_path: Path | None = None,
) -> RunInvocation:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "run":
        argv = argv[1:]

    if not argv:
        return RunInvocation(preset=preset.name, help=True)

    wants_help = "--help" in argv or "-h" in argv
    preset_name, peek_bundle, _ = _peek_command_argv(
        argv, default_preset=preset.name, bundle_path=bundle_path
    )

    manifest = resolve_manifest_for_preset(preset, bundle_path=peek_bundle)
    variant_key = resolve_options_variant(manifest, preset)
    specs = (
        bundle_run_options_for_help(manifest, variant=variant_key)
        if wants_help
        else bundle_run_options(manifest, variant=variant_key)
    )

    if wants_help:
        return RunInvocation(
            preset=preset_name,
            help=True,
            bundle=peek_bundle,
            option_specs=specs,
        )

    ns = _build_run_parser(preset_name, specs).parse_args(argv)
    return RunInvocation(
        preset=preset_name,
        bundle=bundle_path,
        checkpoint=ns.checkpoint,
        mtp_checkpoint=getattr(ns, "mtp_checkpoint", None),
        benchmark=int(ns.benchmark),
        warmup=int(ns.warmup),
        no_auto_install=bool(ns.no_auto_install),
        quiet=bool(ns.quiet),
        bundle_options=_collect_bundle_options(ns, specs),
        option_specs=specs,
    )


def parse_serve_argv(
    argv: list[str] | None = None,
    *,
    preset: Preset,
    bundle_path: Path | None = None,
) -> ServeInvocation:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "serve":
        argv = argv[1:]

    if not argv:
        return ServeInvocation(preset=preset.name, help=True)

    wants_help = "--help" in argv or "-h" in argv
    preset_name, peek_bundle, _ = _peek_command_argv(
        argv, default_preset=preset.name, bundle_path=bundle_path
    )

    manifest = resolve_manifest_for_preset(preset, bundle_path=peek_bundle)
    variant_key = resolve_options_variant(manifest, preset)
    specs = (
        bundle_serve_options_for_help(manifest, variant=variant_key)
        if wants_help
        else bundle_serve_options(manifest, variant=variant_key)
    )

    if wants_help:
        return ServeInvocation(
            preset=preset_name,
            help=True,
            bundle=peek_bundle,
            option_specs=specs,
        )

    ns = _build_serve_parser(preset_name, specs).parse_args(argv)
    return ServeInvocation(
        preset=preset_name,
        bundle=bundle_path,
        checkpoint=ns.checkpoint,
        mtp_checkpoint=getattr(ns, "mtp_checkpoint", None),
        port=int(ns.port),
        host=str(ns.host),
        no_auto_install=bool(ns.no_auto_install),
        quiet=bool(ns.quiet),
        bundle_options=_collect_bundle_options(ns, specs),
        option_specs=specs,
    )
