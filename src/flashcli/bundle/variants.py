"""Multi-model variant sections inside a single ``flashcli-bundle.json``."""

from __future__ import annotations

from typing import Any

from flashcli.bundle.manifest import BundleManifest
from flashcli.models.registry import Preset


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
    """Return active variant key (``qwen3`` / ``qwen36``) for a multi-model bundle."""
    variants = bundle_variants(bundle)
    if not variants:
        legacy = str(bundle.raw.get("variant", "")).strip()
        if legacy:
            return legacy
        if name and str(name).strip():
            return str(name).strip()
        return ""

    default = str(bundle.raw.get("default_variant", "")).strip()
    key = (name or default or next(iter(sorted(variants)))).strip()
    if not key:
        raise BundleVariantError(f"Bundle {bundle.name!r} has variants but no key resolved")
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


def variant_extra_weights(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    extra = variant_section(bundle, variant, "extra_weights")
    if extra:
        return extra
    if not has_bundle_variants(bundle):
        from flashcli.bundle.weights import extra_weights_spec

        return extra_weights_spec(bundle)
    return {}


def variant_env(bundle: BundleManifest, variant: str) -> dict[str, str]:
    env = variant_section(bundle, variant, "env")
    if env:
        return {str(k): str(v) for k, v in env.items()}
    if not has_bundle_variants(bundle):
        from flashcli.bundle.config import bundle_dict

        merged = bundle_dict(bundle, "env")
        return {str(k): str(v) for k, v in merged.items()}
    return {}


def variant_defaults(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    from flashcli.bundle.config import bundle_defaults

    merged.update(bundle_defaults(bundle))
    merged.update(variant_section(bundle, variant, "defaults"))
    return merged


def variant_serve_cfg(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    from flashcli.bundle.config import bundle_dict

    merged.update(bundle_dict(bundle, "serve"))
    merged.update(variant_section(bundle, variant, "serve"))
    return merged


def variant_merged_load_options(
    bundle: BundleManifest,
    variant: str,
    **options: Any,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(variant_defaults(bundle, variant))
    merged.update(variant_serve_cfg(bundle, variant))
    merged.update(options)
    merged["model_variant"] = variant
    return merged


def preset_bundle_variant(preset: Preset) -> str | None:
    """Catalog-level variant key (``models.yaml`` → ``bundle_variant``)."""
    for key in ("bundle_variant", "variant", "model_variant", "model"):
        value = preset.raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_effective_model_variant(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    cli_override: str | None = None,
) -> str | None:
    """CLI ``--model`` > catalog ``bundle_variant`` > bundle ``default_variant``."""
    if cli_override and str(cli_override).strip():
        key = str(cli_override).strip()
        if bundle is not None and has_bundle_variants(bundle):
            resolve_bundle_variant(bundle, key)
        return key
    catalog = preset_bundle_variant(preset)
    if catalog:
        if bundle is not None and has_bundle_variants(bundle):
            resolve_bundle_variant(bundle, catalog)
        return catalog
    if bundle is not None and has_bundle_variants(bundle):
        default = str(bundle.raw.get("default_variant", "")).strip()
        return default or None
    return None
