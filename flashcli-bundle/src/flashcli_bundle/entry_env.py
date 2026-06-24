"""Inject environment variables visible to bundle ``entry`` (engine vs script)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from flashcli_bundle.manifest import BundleManifest, EntryMode
from flashcli_bundle.preset import Preset
from flashcli_bundle.weights import apply_bundle_env, extra_weight_dir, extra_weights_spec

# --- Documented bundle-facing names (script mode) ---
ENV_CHECKPOINT = "FLASHCLI_CHECKPOINT"
ENV_BUNDLE_ROOT = "FLASHCLI_BUNDLE_ROOT"
ENV_PRESET = "FLASHCLI_PRESET"
ENV_VARIANT = "FLASHCLI_VARIANT"
ENV_EXTRA_WEIGHT_PREFIX = "FLASHCLI_EXTRA_WEIGHT_"

# --- Documented engine-only names (also set via manifest ``env`` / post_pull) ---
ENV_MTP_CHECKPOINT = "FLASHRT_QWEN36_MTP_CKPT_DIR"
ENV_PALIGEMMA_TOKENIZER = "FLASH_RT_PALIGEMMA_TOKENIZER"

_SCRIPT_ENV_KEYS = frozenset(
    {
        ENV_CHECKPOINT,
        ENV_BUNDLE_ROOT,
        ENV_PRESET,
        ENV_VARIANT,
    }
)


def extra_weight_env_name(manifest_key: str) -> str:
    """Map manifest ``extra_weights`` key to a stable script-mode env name."""
    safe = re.sub(r"[^A-Z0-9]", "_", manifest_key.upper()).strip("_")
    return f"{ENV_EXTRA_WEIGHT_PREFIX}{safe}"


def _clear_script_entry_env(bundle: BundleManifest, *, variant: str | None) -> None:
    for key in _SCRIPT_ENV_KEYS:
        os.environ.pop(key, None)
    for manifest_key in extra_weights_spec(bundle, variant=variant):
        os.environ.pop(extra_weight_env_name(manifest_key), None)


def inject_script_entry_env(
    *,
    preset: Preset,
    bundle: BundleManifest,
    checkpoint: Path,
    variant: str | None,
) -> None:
    """Expose resolved paths for script ``main()`` — no ``{models_dir}`` templates."""
    _clear_script_entry_env(bundle, variant=variant)
    os.environ[ENV_CHECKPOINT] = str(checkpoint.resolve())
    os.environ[ENV_BUNDLE_ROOT] = str(bundle.bundle_root.resolve())
    os.environ[ENV_PRESET] = preset.name
    if variant:
        os.environ[ENV_VARIANT] = variant
    else:
        os.environ.pop(ENV_VARIANT, None)

    for key, spec in extra_weights_spec(bundle, variant=variant).items():
        if not isinstance(spec, dict):
            continue
        if not str(spec.get("repo", "")).strip():
            continue
        dest = extra_weight_dir(bundle, key, spec)
        os.environ[extra_weight_env_name(key)] = str(dest.resolve())


def inject_engine_entry_env(
    bundle: BundleManifest,
    *,
    variant: str | None,
    mtp_checkpoint: Path | None = None,
) -> None:
    """Apply manifest ``env`` and engine-specific overrides (not used in script mode)."""
    _clear_script_entry_env(bundle, variant=variant)
    apply_bundle_env(bundle, variant=variant)
    if mtp_checkpoint is not None:
        path = mtp_checkpoint.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"MTP checkpoint not found: {path}")
        os.environ[ENV_MTP_CHECKPOINT] = str(path)


def inject_entry_env(
    *,
    mode: EntryMode,
    preset: Preset,
    bundle: BundleManifest,
    checkpoint: Path,
    variant: str | None,
    mtp_checkpoint: Path | None = None,
) -> None:
    if mode == "script":
        inject_script_entry_env(
            preset=preset,
            bundle=bundle,
            checkpoint=checkpoint,
            variant=variant,
        )
        return
    inject_engine_entry_env(
        bundle,
        variant=variant,
        mtp_checkpoint=mtp_checkpoint,
    )
