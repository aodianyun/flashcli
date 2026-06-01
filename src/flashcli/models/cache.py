"""Model cache paths, validation, and ensure/download orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path

from flashcli import config
from flashcli.bundle.manifest import BundleManifest
from flashcli.bundle.resolve import load_preset_bundle
from flashcli.bundle.weights import (
    apply_bundle_env,
    ensure_checkpoint,
    post_pull_steps,
)
from flashcli.models.post_pull import run_post_pull_steps
from flashcli.models.registry import Preset, PresetRegistry


def preset_cache_dir(preset: str) -> Path:
    return config.MODELS_DIR / preset


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


def is_cached(preset: str) -> bool:
    return _checkpoint_from_cache(preset_cache_dir(preset)) is not None


def _apply_mtp_env(
    bundle: BundleManifest | None,
    *,
    mtp_checkpoint_override: Path | None,
    model_variant: str | None = None,
) -> None:
    if mtp_checkpoint_override is not None:
        path = mtp_checkpoint_override.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"MTP checkpoint not found: {path}")
        os.environ["FLASHRT_QWEN36_MTP_CKPT_DIR"] = str(path)
        return
    if bundle is not None:
        apply_bundle_env(bundle, variant=model_variant)


def _load_bundle_for_preset(
    preset: Preset,
    *,
    bundle_path: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint: Path | None = None,
    quiet: bool = False,
) -> BundleManifest | None:
    if preset.engine != "model_bundle":
        return None
    try:
        return load_preset_bundle(
            preset,
            bundle_override=bundle_path,
            bundle_ref=bundle_ref or bundle_version,
            checkpoint=checkpoint,
            fetch_git=bundle_path is None,
            quiet=quiet,
        )
    except FileNotFoundError:
        return None


def ensure_model_cached(
    preset: str,
    *,
    bundle_path: Path | None = None,
    bundle_ref: str | None = None,
    bundle_version: str | None = None,
    checkpoint_override: Path | None = None,
    mtp_checkpoint_override: Path | None = None,
    model_variant: str | None = None,
    quiet: bool = False,
) -> Path:
    """Return checkpoint directory, downloading from HF when missing."""
    reg = PresetRegistry()
    p = reg.get(preset)
    bundle = _load_bundle_for_preset(
        p,
        bundle_path=bundle_path,
        bundle_ref=bundle_ref or bundle_version,
        checkpoint=checkpoint_override,
        quiet=quiet,
    )

    if checkpoint_override is not None:
        path = checkpoint_override.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        if bundle is not None:
            apply_bundle_env(bundle)
        _apply_mtp_env(
            bundle,
            mtp_checkpoint_override=mtp_checkpoint_override,
            model_variant=model_variant,
        )
        if bundle is not None:
            post = post_pull_steps(bundle)
            if post:
                run_post_pull_steps(post, quiet=quiet)
        return path

    ckpt = ensure_checkpoint(
        p,
        bundle,
        checkpoint_override=None,
        variant=model_variant,
        quiet=quiet,
    )
    _apply_mtp_env(
        bundle,
        mtp_checkpoint_override=mtp_checkpoint_override,
        model_variant=model_variant,
    )
    if bundle is not None:
        post = post_pull_steps(bundle)
        if post:
            run_post_pull_steps(post, quiet=quiet)
    return ckpt
