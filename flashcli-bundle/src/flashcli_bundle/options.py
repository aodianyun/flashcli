"""Manifest ``run_options`` / ``serve_options`` parsing and defaults."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Literal

from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.preset import Preset
from flashcli_bundle.variants import (
    bundle_variants,
    has_bundle_variants,
    preset_bundle_variant,
    resolve_bundle_variant,
)

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
            return parse_bool_arg
        return str


def parse_bool_arg(value: str) -> bool:
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
) -> str | None:
    if not has_bundle_variants(bundle):
        return None

    override = (preset_bundle_variant(preset) or "").strip()
    if override:
        return resolve_bundle_variant(bundle, override)

    keys = ", ".join(sorted(bundle_variants(bundle)))
    raise BundleOptionsError(
        f"Bundle {bundle.name!r} has variants ({keys}); add @variant to the preset ref "
        f"(e.g. flashcli-bundle/{bundle.name}:VERSION@{next(iter(sorted(bundle_variants(bundle))), 'VARIANT')})."
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
    if name in overrides and overrides[name] is not None:
        return overrides[name]
    return defaults.get(name)


def validate_bundle_options(bundle: BundleManifest) -> list[str]:
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


def bundle_run_options_for_help(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return bundle_run_options(bundle, variant=variant)


def bundle_serve_options_for_help(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> list[OptionSpec]:
    return bundle_serve_options(bundle, variant=variant)
