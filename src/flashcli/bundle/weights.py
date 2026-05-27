"""Resolve and download model weights declared in a model bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flashcli import config
from flashcli.bundle.checkpoint import has_usable_checkpoint
from flashcli.bundle.config import bundle_dict, bundle_list
from flashcli.bundle.manifest import BundleManifest
from flashcli.bundle.variants import (
    has_bundle_variants,
    resolve_bundle_variant,
    variant_extra_weights,
    variant_weights_dir,
    variant_weights_spec,
)
from flashcli.models.registry import Preset

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


def has_local_weights(path: Path) -> bool:
    if not path.is_dir():
        return False
    if has_usable_checkpoint(path):
        return True
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
    """Weights download spec from ``flashcli-bundle.json`` (or ``variants.<name>``)."""
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_weights_spec(bundle, key)
    return bundle_dict(bundle, "weights")


def extra_weights_spec(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> dict[str, Any]:
    """Extra weights from ``extra_weights`` (legacy alias: ``extra_pull``)."""
    if has_bundle_variants(bundle):
        key = resolve_bundle_variant(bundle, variant)
        return variant_extra_weights(bundle, key)
    extra = bundle_dict(bundle, "extra_weights")
    if extra:
        return extra
    return bundle_dict(bundle, "extra_pull")


def post_pull_steps(bundle: BundleManifest) -> list[Any]:
    return bundle_list(bundle, "post_pull")


def _format_bundle_env(value: str, bundle_root: Path) -> str:
    return value.format(
        models_dir=str(config.MODELS_DIR),
        bundle_root=str(bundle_root.resolve()),
    )


def apply_bundle_env(
    bundle: BundleManifest,
    *,
    variant: str | None = None,
) -> None:
    """Apply ``env`` from ``flashcli-bundle.json`` (top-level or per-variant)."""
    import os

    if has_bundle_variants(bundle):
        from flashcli.bundle.variants import resolve_bundle_variant, variant_env

        key = resolve_bundle_variant(bundle, variant)
        merged = variant_env(bundle, key)
    else:
        merged = bundle_dict(bundle, "env")
    for key, value in merged.items():
        if isinstance(value, str):
            os.environ[key] = _format_bundle_env(value, bundle.bundle_root)


def _extra_dest(
    bundle: BundleManifest | None,
    key: str,
    spec: dict[str, Any],
) -> Path:
    if bundle is not None:
        rel = str(spec.get("relative_dir", "")).strip()
        if rel:
            return (bundle.bundle_root / rel).resolve()
    cache_name = str(spec.get("cache_name", key))
    return config.MODELS_DIR / cache_name


def download_extra_weights(
    bundle: BundleManifest | None,
    *,
    variant: str | None = None,
    quiet: bool = False,
) -> None:
    if bundle is None:
        return
    extra = extra_weights_spec(bundle, variant=variant)
    for key, spec in extra.items():
        if not isinstance(spec, dict):
            continue
        repo = str(spec.get("repo", "")).strip()
        if not repo:
            if not quiet:
                print(f"  extra_weights {key!r}: repo not set, skipping")
            continue
        dest = _extra_dest(bundle, key, spec)
        dest.mkdir(parents=True, exist_ok=True)
        source = str(spec.get("source", "huggingface")).lower()
        if source != "huggingface":
            raise NotImplementedError(f"Unsupported extra weights source: {source!r}")
        from flashcli.models.pull import _download_huggingface

        _download_huggingface(spec, dest, quiet=quiet)


def download_merged_weights(
    spec: dict[str, Any],
    dest: Path,
    *,
    quiet: bool = False,
) -> None:
    if not spec:
        raise ValueError(
            "No weights download spec (set weights in flashcli-bundle.json)"
        )
    source = str(spec.get("source", "huggingface")).lower()
    dest.mkdir(parents=True, exist_ok=True)
    if source == "huggingface":
        from flashcli.models.pull import _download_huggingface

        _download_huggingface(spec, dest, quiet=quiet)
        return
    if source == "url":
        url = str(spec.get("url", "")).strip()
        if not url:
            raise ValueError("weights.url required when source is 'url'")
        raise NotImplementedError(
            "weights.source=url is reserved; use huggingface repo for now"
        )
    raise NotImplementedError(f"Unsupported weights source: {source!r}")


def resolve_checkpoint(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    checkpoint_override: Path | None = None,
    variant: str | None = None,
) -> Path | None:
    """Return checkpoint path without downloading."""
    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        return path if path.exists() else None
    if bundle is not None:
        local = bundle_weights_dir(bundle, variant=variant)
        if has_local_weights(local):
            return local
    cache = config.MODELS_DIR / preset.name
    marker = cache / ".flashcli_model.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            ckpt = Path(str(data.get("checkpoint", ""))).expanduser()
            if ckpt.is_dir() and has_local_weights(ckpt):
                return ckpt.resolve()
        except json.JSONDecodeError:
            pass
    nested = cache / "checkpoint"
    if has_local_weights(nested):
        return nested.resolve()
    return None


def ensure_checkpoint(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    checkpoint_override: Path | None = None,
    variant: str | None = None,
    quiet: bool = False,
) -> Path:
    """Resolve checkpoint: override → bundle-local → cache → download."""
    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        if bundle is not None:
            apply_bundle_env(bundle, variant=variant)
        return path

    if bundle is None:
        raise ValueError(
            f"No bundle for preset {preset.name!r}; weights must come from "
            "flashcli-bundle.json via a resolved model bundle."
        )

    local = bundle_weights_dir(bundle, variant=variant)
    if has_local_weights(local):
        if not quiet:
            print(f"Using bundle-local weights: {local}")
        apply_bundle_env(bundle, variant=variant)
        download_extra_weights(bundle, variant=variant, quiet=quiet)
        return local

    existing = resolve_checkpoint(preset, bundle=bundle, variant=variant)
    if existing is not None:
        if not quiet:
            print(f"Using cached weights: {existing}")
        apply_bundle_env(bundle, variant=variant)
        download_extra_weights(bundle, variant=variant, quiet=quiet)
        return existing

    spec = weights_spec(bundle, variant=variant)
    cache_dir = config.MODELS_DIR / preset.name
    checkpoint_dir = cache_dir / "checkpoint"
    cache_dir.mkdir(parents=True, exist_ok=True)
    download_merged_weights(spec, checkpoint_dir, quiet=quiet)
    download_extra_weights(bundle, variant=variant, quiet=quiet)
    from flashcli.models.pull import _write_marker

    _write_marker(cache_dir, preset.name, checkpoint_dir)
    apply_bundle_env(bundle, variant=variant)
    return checkpoint_dir


def validate_weights_spec(bundle: BundleManifest) -> list[str]:
    """Validate weights section of flashcli-bundle.json."""
    errors: list[str] = []
    if has_bundle_variants(bundle):
        from flashcli.bundle.variants import bundle_variants

        for name in sorted(bundle_variants(bundle)):
            local = bundle_weights_dir(bundle, variant=name)
            if has_local_weights(local):
                continue
            spec = variant_weights_spec(bundle, name)
            if not spec:
                errors.append(
                    f"variants.{name}: no local {local.name}/ and no weights spec"
                )
                continue
            source = str(spec.get("source", "huggingface")).lower()
            if source == "huggingface" and not str(spec.get("repo", "")).strip():
                errors.append(f"variants.{name}.weights.repo is required")
        return errors

    local = bundle_weights_dir(bundle)
    if has_local_weights(local):
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
