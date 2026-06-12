"""Multi-model variant sections inside a single ``flashcli-bundle.json``."""

from __future__ import annotations

from typing import Any

from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.variants import (
    BundleVariantError,
    bundle_variants,
    has_bundle_variants,
    preset_bundle_variant,
    resolve_bundle_variant,
    variant_merged_load_options,
    variant_section,
    variant_weights_dir,
    variant_weights_spec,
)
from flashcli.models.registry import Preset

__all__ = [
    "BundleVariantError",
    "bundle_variants",
    "has_bundle_variants",
    "preset_bundle_variant",
    "resolve_bundle_variant",
    "resolve_effective_model_variant",
    "variant_env",
    "variant_extra_weights",
    "variant_merged_load_options",
    "variant_section",
    "variant_weights_dir",
    "variant_weights_spec",
]


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


def resolve_effective_model_variant(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    cli_override: str | None = None,
) -> str | None:
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
