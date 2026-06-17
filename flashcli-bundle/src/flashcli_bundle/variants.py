"""Multi-model variant sections inside a single ``flashcli-bundle.json``."""

from __future__ import annotations

from typing import Any

from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.preset import Preset


class BundleVariantError(ValueError):
    pass


def bundle_variants(bundle: BundleManifest) -> dict[str, dict[str, Any]]:
    raw = bundle.raw.get("variants")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[str(key)] = dict(value)
    return out


def has_bundle_variants(bundle: BundleManifest) -> bool:
    return bool(bundle_variants(bundle))


def resolve_bundle_variant(
    bundle: BundleManifest,
    name: str | None = None,
) -> str:
    variants = bundle_variants(bundle)
    if not variants:
        if name and str(name).strip():
            return str(name).strip()
        return ""

    key = (name or "").strip()
    if not key:
        keys = ", ".join(sorted(variants))
        raise BundleVariantError(
            f"Bundle {bundle.name!r} has variants; add @variant to the ref "
            f"(choose from: {keys})"
        )
    if key not in variants:
        raise BundleVariantError(
            f"Unknown model variant {key!r} for bundle {bundle.name!r}; "
            f"choose from: {', '.join(sorted(variants))}"
        )
    return key


def variant_section(
    bundle: BundleManifest,
    variant: str,
    section: str,
) -> dict[str, Any]:
    variants = bundle_variants(bundle)
    if variant not in variants:
        return {}
    block = variants[variant].get(section)
    return dict(block) if isinstance(block, dict) else {}


def variant_weights_dir(bundle: BundleManifest, variant: str) -> str:
    rel = str(variant_section(bundle, variant, "weights_dir")).strip()
    if rel:
        return rel
    return f"checkpoint/{variant}"


def variant_weights_spec(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    spec = variant_section(bundle, variant, "weights")
    if spec:
        return spec
    if not has_bundle_variants(bundle):
        raw = bundle.raw.get("weights")
        return dict(raw) if isinstance(raw, dict) else {}
    return {}


def variant_merged_load_options(
    bundle: BundleManifest,
    variant: str,
    **options: Any,
) -> dict[str, Any]:
    from flashcli_bundle.options import serve_option_defaults

    merged = serve_option_defaults(bundle, variant=variant)
    merged.update({k: v for k, v in options.items() if v is not None})
    merged["model_variant"] = variant
    return merged


def preset_bundle_variant(preset: Preset) -> str | None:
    value = preset.raw.get("bundle_variant")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
