"""Bundle-declared CLI options: ``run_options`` and ``serve_options``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, load_bundle_manifest_data
from flashcli.bundle.variants import has_bundle_variants, preset_bundle_variant
from flashcli.models.registry import Preset

OptionPhase = Literal["load", "predict", "warmup"]
OPTIONS_KEY = Literal["run_options", "serve_options"]


class BundleOptionsError(ValueError):
    """Invalid or missing ``run_options`` / ``serve_options`` in manifest."""


@dataclass(frozen=True)
class OptionSpec:
    name: str
    flag: str
    type: str
    help: str
    phase: OptionPhase = "predict"
    default: Any = None
    variant: str | None = None

    def argparse_type(self) -> type | Any:
        if self.type == "integer":
            return int
        if self.type == "float":
            return float
        if self.type == "boolean":
            return _parse_bool
        return str


def _parse_bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected boolean, got {value!r}")


def _parse_option_dict(
    raw: dict[str, Any],
    *,
    variant: str | None = None,
    valid_phases: frozenset[str],
    default_phase: str,
) -> OptionSpec | None:
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    flag = str(raw.get("flag", name.replace("_", "-"))).strip().lstrip("-")
    opt_type = str(raw.get("type", "string")).strip().lower()
    if opt_type not in ("string", "integer", "float", "boolean"):
        opt_type = "string"
    phase = str(raw.get("phase", default_phase)).strip().lower()
    if phase not in valid_phases:
        phase = default_phase
    help_text = str(raw.get("help", "")).strip()
    default = raw.get("default", argparse.SUPPRESS)
    return OptionSpec(
        name=name,
        flag=flag,
        type=opt_type,
        help=help_text,
        phase=phase,  # type: ignore[arg-type]
        default=default,
        variant=variant,
    )


def _options_from_list(
    raw: list[Any],
    *,
    variant: str | None = None,
    valid_phases: frozenset[str],
    default_phase: str,
) -> list[OptionSpec]:
    out: list[OptionSpec] = []
    for item in raw:
        if isinstance(item, dict):
            spec = _parse_option_dict(
                item,
                variant=variant,
                valid_phases=valid_phases,
                default_phase=default_phase,
            )
            if spec is not None:
                out.append(spec)
    return out


_RUN_PHASES = frozenset({"load", "predict"})
_SERVE_PHASES = frozenset({"load", "warmup"})


def _options_for_variant(
    bundle: BundleManifest,
    variant: str,
    key: OPTIONS_KEY,
) -> list[OptionSpec]:
    from flashcli.bundle.variants import bundle_variants

    variants = bundle_variants(bundle)
    block = variants.get(variant, {}).get(key)
    if isinstance(block, list):
        if key == "run_options":
            return _options_from_list(
                block, variant=variant, valid_phases=_RUN_PHASES, default_phase="predict"
            )
        return _options_from_list(
            block, variant=variant, valid_phases=_SERVE_PHASES, default_phase="load"
        )
    return []


def _reject_top_level_options_with_variants(bundle: BundleManifest, key: OPTIONS_KEY) -> None:
    if not has_bundle_variants(bundle):
        return
    raw = bundle.raw.get(key)
    if isinstance(raw, list) and raw:
        raise BundleOptionsError(
            f"Bundle {bundle.name!r} defines variants; {key} must be declared "
            f"under each variant, not at bundle root."
        )


def resolve_options_variant(
    bundle: BundleManifest,
    preset: Preset,
    *,
    cli_model: str | None = None,
) -> str | None:
    """Variant key for option lookup (None when bundle has no variants)."""
    if not has_bundle_variants(bundle):
        return None

    from flashcli.bundle.variants import bundle_variants, resolve_bundle_variant

    override = (cli_model or preset_bundle_variant(preset) or "").strip()
    if override:
        return resolve_bundle_variant(bundle, override)

    default = str(bundle.raw.get("default_variant", "")).strip()
    if default:
        return resolve_bundle_variant(bundle, default)

    keys = ", ".join(sorted(bundle_variants(bundle)))
    raise BundleOptionsError(
        f"Bundle {bundle.name!r} has variants ({keys}); set catalog bundle_variant, "
        f"pass --model, or define default_variant."
    )


def _bundle_options(
    bundle: BundleManifest,
    key: OPTIONS_KEY,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    _reject_top_level_options_with_variants(bundle, key)

    if has_bundle_variants(bundle):
        if not variant:
            raise BundleOptionsError(
                f"Bundle {bundle.name!r} has variants; variant is required for {key}."
            )
        return _options_for_variant(bundle, variant, key)

    if key == "run_options":
        valid_phases, default_phase = _RUN_PHASES, "predict"
    else:
        valid_phases, default_phase = _SERVE_PHASES, "load"

    raw = bundle.raw.get(key)
    if isinstance(raw, list):
        return _options_from_list(
            raw, valid_phases=valid_phases, default_phase=default_phase
        )
    return []


def bundle_run_options(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return _bundle_options(bundle, "run_options", variant=variant)


def bundle_serve_options(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return _bundle_options(bundle, "serve_options", variant=variant)


def _option_defaults(specs: list[OptionSpec]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for spec in specs:
        if spec.default is not argparse.SUPPRESS:
            out[spec.name] = spec.default
    return out


def run_option_defaults(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    return _option_defaults(bundle_run_options(bundle, variant=variant))


def serve_option_defaults(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    return _option_defaults(bundle_serve_options(bundle, variant=variant))


def option_value(
    name: str,
    overrides: dict[str, Any],
    defaults: dict[str, Any],
) -> Any:
    """Resolve one manifest option: explicit override wins, then manifest default."""
    if name in overrides and overrides[name] is not None:
        return overrides[name]
    return defaults.get(name)


def validate_bundle_options(bundle: BundleManifest) -> list[str]:
    """Validate ``run_options`` / ``serve_options`` layout rules."""
    from flashcli.bundle.variants import bundle_variants

    errors: list[str] = []
    has_run = bundle.entry_run is not None
    has_serve = bundle.entry_serve is not None
    multi = has_bundle_variants(bundle)

    if multi:
        for key in ("run_options", "serve_options"):
            block = bundle.raw.get(key)
            if isinstance(block, list) and block:
                errors.append(
                    f"top-level {key} is not allowed when variants are defined; "
                    f"declare options under each variants.<name>."
                )
        for name, block in sorted(bundle_variants(bundle).items()):
            if has_run:
                ro = block.get("run_options")
                if not isinstance(ro, list) or not ro:
                    errors.append(
                        f"variants.{name} missing run_options (required for entry.run)"
                    )
                else:
                    for spec in bundle_run_options(bundle, variant=name):
                        if not spec.help:
                            errors.append(
                                f"variants.{name}.run_options.{spec.name} missing help"
                            )
            if has_serve:
                so = block.get("serve_options")
                if not isinstance(so, list) or not so:
                    errors.append(
                        f"variants.{name} missing serve_options (required for entry.serve)"
                    )
                else:
                    for spec in bundle_serve_options(bundle, variant=name):
                        if not spec.help:
                            errors.append(
                                f"variants.{name}.serve_options.{spec.name} missing help"
                            )
    else:
        if has_run:
            ro = bundle.raw.get("run_options")
            if not isinstance(ro, list) or not ro:
                errors.append("missing top-level run_options (required for entry.run)")
            else:
                for spec in bundle_run_options(bundle):
                    if not spec.help:
                        errors.append(f"run_options.{spec.name} missing help")
        if has_serve:
            so = bundle.raw.get("serve_options")
            if not isinstance(so, list) or not so:
                errors.append("missing top-level serve_options (required for entry.serve)")
            else:
                for spec in bundle_serve_options(bundle):
                    if not spec.help:
                        errors.append(f"serve_options.{spec.name} missing help")

    return errors


def resolve_manifest_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
) -> BundleManifest:
    """Load ``flashcli-bundle.json`` for help/parse (no runtime download)."""
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


def split_run_options(
    values: dict[str, Any],
    specs: list[OptionSpec],
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_name = {s.name: s for s in specs}
    load_kw: dict[str, Any] = {}
    predict_kw: dict[str, Any] = {}
    for key, value in values.items():
        spec = by_name.get(key)
        if spec is None:
            continue
        if spec.phase == "load":
            load_kw[key] = value
        else:
            predict_kw[key] = value
    return load_kw, predict_kw


def split_serve_options(
    values: dict[str, Any],
    specs: list[OptionSpec],
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_name = {s.name: s for s in specs}
    load_kw: dict[str, Any] = {}
    warmup_kw: dict[str, Any] = {}
    for key, value in values.items():
        spec = by_name.get(key)
        if spec is None:
            continue
        if spec.phase == "warmup":
            warmup_kw[key] = value
        else:
            load_kw[key] = value
    return load_kw, warmup_kw


def _add_spec_to_parser(parser: argparse.ArgumentParser, spec: OptionSpec) -> None:
    flag = f"--{spec.flag}"
    kwargs: dict[str, Any] = {"dest": spec.name, "help": spec.help}
    if spec.type == "boolean":
        kwargs["type"] = _parse_bool
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


def _options_for_help(
    bundle: BundleManifest,
    key: OPTIONS_KEY,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    getter = bundle_run_options if key == "run_options" else bundle_serve_options
    return getter(bundle, variant=variant)


def bundle_run_options_for_help(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return _options_for_help(bundle, "run_options", variant=variant)


def bundle_serve_options_for_help(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return _options_for_help(bundle, "serve_options", variant=variant)


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
