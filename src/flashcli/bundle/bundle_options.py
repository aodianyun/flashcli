"""CLI argv parsing for bundle-declared ``run_options`` / ``serve_options``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flashcli_bundle.manifest import BundleManifest, load_bundle_manifest, load_bundle_manifest_data
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
from flashcli.models.registry import Preset

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
    "resolve_options_variant",
    "run_option_defaults",
    "serve_option_defaults",
    "split_run_options",
    "split_serve_options",
    "validate_bundle_options",
]


def resolve_manifest_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> BundleManifest:
    from flashcli import config
    from flashcli.bundle.catalog import raw_bundle_cfg, repo_url_for_preset
    from flashcli.bundle.flashhub import download_manifest_from_repo
    from flashcli.bundle.layout import is_bundle_root
    from flashcli.bundle.marker import read_preset_marker

    if bundle_path is not None:
        root = bundle_path.expanduser().resolve()
        if is_bundle_root(root):
            return load_bundle_manifest(root)

    cfg = raw_bundle_cfg(preset)
    path_str = str(cfg.get("path", "")).strip()
    if path_str:
        root = Path(path_str).expanduser()
        if not root.is_absolute():
            root = (config.package_root() / root).resolve()
        if is_bundle_root(root):
            return load_bundle_manifest(root)

    marker = read_preset_marker(preset.name) or {}
    cached_root = str(marker.get("bundle_root", "")).strip()
    if cached_root:
        root = Path(cached_root).expanduser().resolve()
        if is_bundle_root(root):
            return load_bundle_manifest(root)

    repo = str(cfg.get("repo", "")).strip()
    if not repo:
        if bundle_path is not None:
            raise FileNotFoundError(f"Bundle root not found: {bundle_path}")
        raise FileNotFoundError(
            f"Preset {preset.name!r} has no bundle.repo/path and no cached bundle"
        )

    import tempfile

    tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{preset.name}.json"
    data = download_manifest_from_repo(repo_url_for_preset(preset), tmp, quiet=True)
    root = Path(cached_root) if cached_root else tmp.parent
    return load_bundle_manifest_data(data, bundle_root=root)


COMMON_RUN_OPTIONS_HELP: list[tuple[str, str]] = [
    ("PRESET", "Model preset name (from catalog)."),
    ("--bundle PATH", "Override bundle root (local dev tree)."),
    ("--checkpoint PATH", "Override checkpoint directory (skip cache/download)."),
    (
        "--mtp-checkpoint PATH",
        "Override MTP weights dir (sets FLASHRT_QWEN36_MTP_CKPT_DIR).",
    ),
    ("--model NAME", "Override catalog bundle_variant (e.g. qwen3, qwen36)."),
    ("--benchmark N", "Timed predict iterations after the first run."),
    (
        "--warmup N",
        "Extra predict iterations before --benchmark (orchestration warmup).",
    ),
    ("--no-auto-install", "Do not auto-install bundle Python deps."),
    ("--quiet, -q", "Less output."),
]

COMMON_SERVE_OPTIONS_HELP: list[tuple[str, str]] = [
    ("PRESET", "Model preset name (from catalog)."),
    ("--bundle PATH", "Override bundle root (local dev tree)."),
    ("--checkpoint PATH", "Override checkpoint directory."),
    ("--mtp-checkpoint PATH", "Override MTP weights dir."),
    ("--model NAME", "Override catalog bundle_variant."),
    ("--port PORT", "HTTP listen port (default: 8000)."),
    ("--host HOST", "HTTP listen address (default: 0.0.0.0)."),
    ("--no-auto-install", "Do not auto-install bundle Python deps."),
    ("--quiet, -q", "Less output."),
]


def _format_options_help(
    title: str,
    specs: list[OptionSpec],
    *,
    default_phase: str,
) -> list[str]:
    lines = [title]
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
) -> str:
    lines = [
        f"Usage: flashcli run {preset.name} [COMMON OPTIONS] [BUNDLE OPTIONS]",
        "",
        manifest.description or preset.description or "",
        "",
        "Common options (flashcli):",
    ]
    for flag, text in COMMON_RUN_OPTIONS_HELP:
        lines.append(f"  {flag:<24}  {text}")
    lines.append("")
    lines.extend(_format_options_help("Bundle run options:", specs, default_phase="predict"))
    lines.append("")
    lines.append("Use flashcli models envs to check runtime GPU/CUDA support.")
    return "\n".join(lines)


def format_serve_help(
    preset: Preset,
    manifest: BundleManifest,
    specs: list[OptionSpec],
) -> str:
    lines = [
        f"Usage: flashcli serve {preset.name} [COMMON OPTIONS] [BUNDLE OPTIONS]",
        "",
        manifest.description or preset.description or "",
        "",
        "Common options (flashcli):",
    ]
    for flag, text in COMMON_SERVE_OPTIONS_HELP:
        lines.append(f"  {flag:<24}  {text}")
    lines.append("")
    lines.extend(_format_options_help("Bundle serve options:", specs, default_phase="load"))
    lines.append("")
    lines.append("Use flashcli models envs to check runtime GPU/CUDA support.")
    return "\n".join(lines)


@dataclass
class RunInvocation:
    preset: str
    help: bool = False
    bundle: Path | None = None
    checkpoint: Path | None = None
    mtp_checkpoint: Path | None = None
    model: str | None = None
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
    model: str | None = None
    port: int = 8000
    host: str = "0.0.0.0"
    no_auto_install: bool = False
    quiet: bool = False
    bundle_options: dict[str, Any] | None = None
    option_specs: list[OptionSpec] | None = None


def _peek_command_argv(
    argv: list[str],
    *,
    default_preset: str,
    bundle_path: Path | None,
) -> tuple[str, Path | None, str | None]:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("preset", nargs="?")
    pre.add_argument("--bundle", type=Path, dest="bundle")
    pre.add_argument("--model")
    ns, _ = pre.parse_known_args(argv)
    preset_name = ns.preset or default_preset
    if ns.preset is None and argv and not argv[0].startswith("-"):
        preset_name = argv[0]
    return preset_name, ns.bundle or bundle_path, ns.model


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
    parser.add_argument("preset", nargs="?", default=preset_name)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--mtp-checkpoint", dest="mtp_checkpoint", type=Path)
    parser.add_argument("--model")
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
    parser.add_argument("preset", nargs="?", default=preset_name)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--mtp-checkpoint", dest="mtp_checkpoint", type=Path)
    parser.add_argument("--model")
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
    preset_name, peek_bundle, peek_model = _peek_command_argv(
        argv, default_preset=preset.name, bundle_path=bundle_path
    )

    manifest = resolve_manifest_for_preset(preset, bundle_path=peek_bundle)
    variant_key = resolve_options_variant(manifest, preset, cli_model=peek_model)
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
        bundle=ns.bundle or bundle_path,
        checkpoint=ns.checkpoint,
        mtp_checkpoint=getattr(ns, "mtp_checkpoint", None),
        model=ns.model,
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
    preset_name, peek_bundle, peek_model = _peek_command_argv(
        argv, default_preset=preset.name, bundle_path=bundle_path
    )

    manifest = resolve_manifest_for_preset(preset, bundle_path=peek_bundle)
    variant_key = resolve_options_variant(manifest, preset, cli_model=peek_model)
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
        bundle=ns.bundle or bundle_path,
        checkpoint=ns.checkpoint,
        mtp_checkpoint=getattr(ns, "mtp_checkpoint", None),
        model=ns.model,
        port=int(ns.port),
        host=str(ns.host),
        no_auto_install=bool(ns.no_auto_install),
        quiet=bool(ns.quiet),
        bundle_options=_collect_bundle_options(ns, specs),
        option_specs=specs,
    )
