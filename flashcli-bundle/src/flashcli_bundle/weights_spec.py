"""Weights manifest validation (shared by host sync and bundle layout checks)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flashcli_bundle.bundle_config import bundle_dict
from flashcli_bundle.checkpoint import (
    has_checkpoint_weight_files,
    has_usable_checkpoint,
    weights_require_norm_stats,
)
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.variants import (
    bundle_variants,
    has_bundle_variants,
    resolve_bundle_variant,
    variant_weights_dir,
    variant_weights_spec,
)

_SKIP_WEIGHT_NAMES = frozenset({".flashcli_model.json", ".gitkeep"})


def bundle_weights_dir(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> Path:
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        rel = variant_weights_dir(bundle, key)
    else:
        rel = str(bundle.raw.get("weights_dir", "checkpoint")).strip() or "checkpoint"
    return (bundle.bundle_root / rel).resolve()


def has_local_weights(
    path: Path,
    *,
    weights_spec: dict[str, Any] | None = None,
) -> bool:
    if not path.is_dir():
        return False
    require_ns = weights_require_norm_stats(weights_spec)
    if has_usable_checkpoint(path, require_norm_stats=require_ns):
        return True
    if require_ns and has_checkpoint_weight_files(path):
        return False
    for entry in path.iterdir():
        if entry.name in _SKIP_WEIGHT_NAMES or entry.name.startswith("."):
            continue
        if entry.name == ".cache":
            continue
        if entry.is_file():
            return True
        if entry.is_dir() and has_usable_checkpoint(entry):
            return True
    return False


def weights_spec(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_weights_spec(bundle, key)
    return bundle_dict(bundle, "weights")


def validate_weights_spec(bundle: BundleManifest) -> list[str]:
    """Validate weights section of flashcli-bundle.json."""
    errors: list[str] = []
    if has_bundle_variants(bundle):
        for name in sorted(bundle_variants(bundle)):
            spec = variant_weights_spec(bundle, name)
            local = bundle_weights_dir(bundle, variant=name)
            if has_local_weights(local, weights_spec=spec):
                continue
            if not spec:
                errors.append(
                    f"variants.{name}: no local {local.name}/ and no weights spec"
                )
                continue
            source = str(spec.get("source", "huggingface")).lower()
            if source == "huggingface" and not str(spec.get("repo", "")).strip():
                errors.append(f"variants.{name}.weights.repo is required")
        return errors

    spec = weights_spec(bundle)
    local = bundle_weights_dir(bundle)
    if has_local_weights(local, weights_spec=spec):
        return errors

    weights = bundle.raw.get("weights")
    if not isinstance(weights, dict) or not weights:
        errors.append(
            "weights: no local checkpoint/ (or weights/) and no weights download "
            "spec in flashcli-bundle.json — add weights.repo or ship weights in the bundle"
        )
        return errors

    source = str(weights.get("source", "huggingface")).lower()
    if source == "huggingface":
        if not str(weights.get("repo", "")).strip():
            errors.append("weights.repo is required when source is huggingface")
    elif source == "url":
        if not str(weights.get("url", "")).strip():
            errors.append("weights.url is required when source is url")
    else:
        errors.append(f"unsupported weights.source: {source!r}")
    return errors
