"""Multi-model variant sections inside a single ``flashcli-bundle.json``."""

from __future__ import annotations

import hashlib
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


def _derived_weights_dir(name: str, spec: dict[str, Any]) -> str:
    """Derive a checkpoint-relative weights dir from the weights identity.

    Mirrors the host's ``manifest.VariantWeightsRel`` (Go): an explicit
    ``weights_dir`` wins; otherwise a directory derived from source/repo/
    revision/url/relative_dir so identical weights share a directory and
    different weights never collide; ``checkpoint/<name>`` when the spec is
    local/uncertain.
    """
    source = str(spec.get("source", "huggingface")).strip().lower() or "huggingface"
    repo = str(spec.get("repo", "")).strip()
    revision = str(spec.get("revision", "")).strip() or "main"
    url = str(spec.get("url", "")).strip()
    relative = str(spec.get("relative_dir", "")).strip()
    if not repo and not url and not relative:
        return f"checkpoint/{name}"
    digest = hashlib.sha256(
        "|".join([source, repo, revision, url, relative]).encode()
    ).hexdigest()[:12]
    return f"checkpoint/{digest}"


def variant_block(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    """Raw variant block (scalars included, unlike :func:`variant_section`)."""
    return bundle_variants(bundle).get(variant, {})


def variant_weights_dir(bundle: BundleManifest, variant: str) -> str:
    block = variant_block(bundle, variant)
    rel = str(block.get("weights_dir", "")).strip()
    if rel:
        return rel.strip("/")
    spec = block.get("weights")
    return _derived_weights_dir(variant, spec if isinstance(spec, dict) else {})


def bundle_weights_rel(bundle: BundleManifest, variant: str | None = None) -> str:
    """Checkpoint-relative weights directory for a bundle/variant.

    Single-variant (no ``variants`` block) bundles use the top-level
    ``weights_dir`` (default ``checkpoint``).
    """
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_weights_dir(bundle, key)
    raw_rel = str(bundle.raw.get("weights_dir", "")).strip().strip("/")
    if raw_rel:
        return raw_rel
    try:
        version = int(bundle.raw.get("format_version", 3))
    except (TypeError, ValueError):
        version = 3
    # v4 default: main weights live at the weights-store root.
    return "" if version >= 4 else "checkpoint"


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


def variant_extra_weights(bundle: BundleManifest, variant: str) -> dict[str, Any]:
    extra = variant_section(bundle, variant, "extra_weights")
    if extra:
        return extra
    if not has_bundle_variants(bundle):
        from flashcli_bundle.bundle_config import bundle_dict

        return bundle_dict(bundle, "extra_weights")
    return {}


def variant_env(bundle: BundleManifest, variant: str) -> dict[str, str]:
    env = variant_section(bundle, variant, "env")
    if env:
        return {str(k): str(v) for k, v in env.items()}
    if not has_bundle_variants(bundle):
        from flashcli_bundle.bundle_config import bundle_dict

        merged = bundle_dict(bundle, "env")
        return {str(k): str(v) for k, v in merged.items()}
    return {}


def validate_required_variant(preset: Preset, bundle: BundleManifest) -> None:
    if not has_bundle_variants(bundle):
        return
    variant = preset_bundle_variant(preset)
    if variant:
        resolve_bundle_variant(bundle, variant)
        return
    keys = ", ".join(sorted(bundle_variants(bundle)))
    raise BundleVariantError(
        f"Bundle {bundle.name!r} has multiple variants; add @variant to the preset ref "
        f"(choose from: {keys}). "
        f"Example: flashcli-bundle/{bundle.name}:VERSION@qwen36"
    )


def resolve_effective_model_variant(
    preset: Preset,
    bundle: BundleManifest | None = None,
) -> str | None:
    catalog = preset_bundle_variant(preset)
    if catalog:
        if bundle is not None and has_bundle_variants(bundle):
            resolve_bundle_variant(bundle, catalog)
        return catalog
    if bundle is not None and has_bundle_variants(bundle):
        validate_required_variant(preset, bundle)
    return None
