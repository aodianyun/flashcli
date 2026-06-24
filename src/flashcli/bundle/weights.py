"""Resolve and download model weights (host: HuggingFace / ModelScope download)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flashcli.models.pull import _allow_patterns, _write_marker, download_weights
from flashcli_bundle import weights as _w
from flashcli_bundle.checkpoint import has_cached_weight_files, weights_require_norm_stats
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.preset import Preset

apply_bundle_env = _w.apply_bundle_env
bundle_weights_dir = _w.bundle_weights_dir
extra_weights_spec = _w.extra_weights_spec
has_local_weights = _w.has_local_weights
post_pull_steps = _w.post_pull_steps
resolve_checkpoint = _w.resolve_checkpoint
weights_spec = _w.weights_spec


def download_extra_weights(
    bundle: BundleManifest | None,
    *,
    variant: str | None = None,
    quiet: bool = False,
    download: bool = True,
) -> None:
    if bundle is None or not download:
        if bundle is not None:
            _w.require_extra_weights_cached(bundle, variant=variant)
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
        rel = str(spec.get("relative_dir", "")).strip()
        if rel:
            dest = (bundle.bundle_root / rel).resolve()
        else:
            cache_name = str(spec.get("cache_name", key))
            from flashcli_bundle import paths as config

            dest = config.MODELS_DIR / cache_name
        dest.mkdir(parents=True, exist_ok=True)
        patterns = _allow_patterns(spec)
        require_ns = weights_require_norm_stats(spec)
        if has_cached_weight_files(dest, patterns, require_norm_stats=require_ns):
            continue
        download_weights(spec, dest, quiet=quiet)


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
    dest.mkdir(parents=True, exist_ok=True)
    download_weights(spec, dest, quiet=quiet)


def ensure_checkpoint(
    preset: Preset,
    bundle: BundleManifest | None = None,
    *,
    checkpoint_override: Path | None = None,
    variant: str | None = None,
    quiet: bool = False,
    download: bool = True,
) -> Path:
    if not download:
        return _w.ensure_checkpoint(
            preset,
            bundle,
            checkpoint_override=checkpoint_override,
            variant=variant,
            quiet=quiet,
            download=False,
        )

    if checkpoint_override is not None:
        return _w.ensure_checkpoint(
            preset,
            bundle,
            checkpoint_override=checkpoint_override,
            variant=variant,
            quiet=quiet,
            download=False,
        )

    if bundle is None:
        raise ValueError(
            f"No bundle for preset {preset.name!r}; weights must come from "
            "flashcli-bundle.json via a resolved model bundle."
        )

    spec = weights_spec(bundle, variant=variant)
    local = bundle_weights_dir(bundle, variant=variant)
    if has_local_weights(local, weights_spec=spec):
        if not quiet:
            print(f"Using bundle-local weights: {local}")
        download_extra_weights(bundle, variant=variant, quiet=quiet, download=True)
        return local

    existing = resolve_checkpoint(preset, bundle=bundle, variant=variant)
    if existing is not None:
        if not quiet:
            print(f"Using cached weights: {existing}")
        download_extra_weights(bundle, variant=variant, quiet=quiet, download=True)
        return existing

    from flashcli_bundle import paths as config
    from flashcli_bundle.preset_ref import preset_cache_key

    cache_dir = config.MODELS_DIR / preset_cache_key(preset)
    checkpoint_dir = cache_dir / "checkpoint"
    cache_dir.mkdir(parents=True, exist_ok=True)
    download_merged_weights(spec, checkpoint_dir, quiet=quiet)
    download_extra_weights(bundle, variant=variant, quiet=quiet, download=True)
    _write_marker(cache_dir, preset.name, checkpoint_dir)
    return checkpoint_dir


__all__ = [
    "apply_bundle_env",
    "bundle_weights_dir",
    "download_extra_weights",
    "download_merged_weights",
    "ensure_checkpoint",
    "extra_weights_spec",
    "has_local_weights",
    "post_pull_steps",
    "resolve_checkpoint",
    "weights_spec",
]
