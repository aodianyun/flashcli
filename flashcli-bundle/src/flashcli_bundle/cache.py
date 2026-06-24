"""Model cache paths, validation, and ensure/download orchestration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from flashcli_bundle import paths as config
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.post_pull import run_post_pull_steps
from flashcli_bundle.preset import Preset
from flashcli_bundle.preset_ref import preset_cache_key, resolve_preset
from flashcli_bundle.resolve import load_preset_bundle
from flashcli_bundle.weights import (
    ensure_checkpoint,
    post_pull_steps,
)

EnsureCheckpointFn = Callable[..., Path]


def preset_cache_dir(preset: Preset | str) -> Path:
    if isinstance(preset, Preset):
        key = preset_cache_key(preset)
    else:
        key = resolve_preset(preset).cache_key
    return config.MODELS_DIR / key


def _read_marker(cache: Path) -> dict | None:
    marker = cache / ".flashcli_model.json"
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _checkpoint_from_cache(cache: Path) -> Path | None:
    marker = _read_marker(cache)
    if marker:
        ckpt = Path(str(marker.get("checkpoint", ""))).expanduser()
        if ckpt.is_dir():
            return ckpt
    nested = cache / "checkpoint"
    if nested.is_dir() and any(nested.iterdir()):
        return nested
    if cache.is_dir() and any(cache.iterdir()):
        skip = {".flashcli_model.json"}
        if any(p.name not in skip for p in cache.iterdir()):
            return cache
    return None


def is_cached(preset: Preset | str) -> bool:
    return _checkpoint_from_cache(preset_cache_dir(preset)) is not None


def _load_bundle_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    quiet: bool = False,
) -> BundleManifest | None:
    if preset.engine != "model_bundle":
        return None
    try:
        return load_preset_bundle(preset, bundle_override=bundle_path)
    except FileNotFoundError:
        return None


def ensure_model_cached(
    preset: Preset | str,
    *,
    bundle_path: Path | None = None,
    checkpoint_override: Path | None = None,
    mtp_checkpoint_override: Path | None = None,
    model_variant: str | None = None,
    quiet: bool = False,
    download: bool = True,
    ensure_checkpoint_fn: EnsureCheckpointFn | None = None,
) -> Path:
    """Return checkpoint directory (resolve-only; host injects download via *ensure_checkpoint_fn*)."""
    if isinstance(preset, str):
        ref = preset
        p = resolve_preset(preset)
    else:
        p = preset
        ref = p.name
    if download and os.environ.get("FLASHCLI_IN_BUNDLE_VENV") == "1":
        raise RuntimeError(
            "Weight download is only supported on the host flashcli CLI. "
            f"Run: flashcli pull {ref}"
        )
    bundle = _load_bundle_for_preset(
        p,
        bundle_path=bundle_path,
        quiet=quiet,
    )

    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        if bundle is not None:
            post = post_pull_steps(bundle)
            if post:
                run_post_pull_steps(post, quiet=quiet)
        return path

    fn = ensure_checkpoint_fn or ensure_checkpoint
    ckpt = fn(
        p,
        bundle,
        checkpoint_override=None,
        variant=model_variant,
        quiet=quiet,
        download=download,
    )
    if bundle is not None:
        post = post_pull_steps(bundle)
        if post:
            run_post_pull_steps(post, quiet=quiet)
    return ckpt
