"""Offline Hugging Face hooks for vendored gr00t (bundle-local, no numpy)."""

from __future__ import annotations

import os
from pathlib import Path

_COSMOS_ENV = "FLASHCLI_EXTRA_WEIGHT_COSMOS_BACKBONE"
_VLM_HUB_MARKERS = ("Cosmos-Reason2", "Qwen3-VL")


def prepare_gr00t_n17_hub_env() -> None:
    """Offline-safe gr00t HF hooks (must run before ``import gr00t``)."""
    os.environ.setdefault("GROOT_HF_LOCAL_FIRST", "1")
    os.environ.setdefault("GROOT_SKIP_HF_MODEL_WEIGHTS", "1")
    os.environ.setdefault("GROOT_PATCH_MISTRAL", "1")
    os.environ.setdefault("GROOT_HF_QUIET", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")


def resolve_vlm_model_path(model_name: str) -> str:
    """Map Cosmos/Qwen3-VL hub ids to vendored ``extra_weights`` on disk."""
    if not any(marker in model_name for marker in _VLM_HUB_MARKERS):
        return model_name
    raw = os.environ.get(_COSMOS_ENV, "").strip()
    if not raw:
        return model_name
    local = Path(raw).expanduser().resolve()
    if local.is_dir() and (local / "config.json").is_file():
        return str(local)
    return model_name
