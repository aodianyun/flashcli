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


def _catalog_repo_url(cfg: dict[str, Any]) -> str:
    return str(cfg.get("repo", "")).strip()


def _try_load_bundle_manifest(root: Path) -> BundleManifest | None:
    from flashcli_bundle.layout import is_bundle_root

    if not is_bundle_root(root):
        return None
    try:
        return load_bundle_manifest(root)
    except ValueError:
        return None


def resolve_manifest_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> BundleManifest:
    import os

    from flashcli_bundle.catalog import raw_bundle_cfg, repo_url_for_preset
    from flashcli_bundle.infer.bundle.flashhub import download_manifest_from_repo
    from flashcli_bundle.layout import is_bundle_root
    from flashcli_bundle.infer.bundle.marker import read_preset_marker
    from flashcli_bundle.preset_ref import preset_cache_key

    env_root = os.environ.get("FLASHCLI_BUNDLE_ROOT", "").strip()
    if env_root:
        manifest = _try_load_bundle_manifest(Path(env_root).expanduser().resolve())
        if manifest is not None:
            return manifest

    if bundle_path is not None:
        root = bundle_path.expanduser().resolve()
        if is_bundle_root(root):
            return load_bundle_manifest(root)

    cfg = raw_bundle_cfg(preset)
    marker = read_preset_marker(preset) or {}
    catalog_repo = _catalog_repo_url(cfg)
    marker_repo = str(marker.get("repo", "")).strip()
    cached_root = str(marker.get("bundle_root", "")).strip()
    cache_repo_matches = not catalog_repo or not marker_repo or marker_repo == catalog_repo

    if cached_root and cache_repo_matches:
        manifest = _try_load_bundle_manifest(Path(cached_root).expanduser().resolve())
        if manifest is not None:
            return manifest

    repo = catalog_repo
    if not repo:
        if bundle_path is not None:
            raise FileNotFoundError(f"Bundle root not found: {bundle_path}")
        raise FileNotFoundError(
            f"Preset {preset.name!r} has no bundle.repo and no cached bundle"
        )

    import tempfile

    key = preset_cache_key(preset)
    tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{key}.json"
    data = download_manifest_from_repo(repo_url_for_preset(preset), tmp, quiet=True)
    root = Path(cached_root) if cached_root else tmp.parent
    return load_bundle_manifest_data(data, bundle_root=root)


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
