"""Checkpoint directory detection (shared by weights download and bundle resolve)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_CHECKPOINT_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.bin",
)

_NORM_STATS_JSON_CANDIDATES = (
    "assets/physical-intelligence/libero/norm_stats.json",
    "assets/droid/norm_stats.json",
    "norm_stats.json",
    "meta/stats.json",
    "stats.json",
)


def weights_require_norm_stats(spec: dict[str, Any] | None) -> bool:
    """Whether a downloaded checkpoint must include norm-stats sidecars."""
    if not spec:
        return False
    if spec.get("require_norm_stats") is True:
        return True
    if spec.get("require_norm_stats") is False:
        return False
    repo = str(spec.get("repo", "")).lower()
    return any(token in repo for token in ("pi05", "pi0_libero", "pi0_"))


def has_norm_stats_sources(path: Path) -> bool:
    """True when openpi JSON or lerobot policy processor safetensors are present."""
    if not path.is_dir():
        return False
    for rel in _NORM_STATS_JSON_CANDIDATES:
        if (path / rel).is_file():
            return True
    pre = list(path.glob("policy_*_normalizer_processor.safetensors"))
    post = list(path.glob("policy_*_unnormalizer_processor.safetensors"))
    return bool(pre and post)


def _matches_allow_pattern(path: Path, pattern: str) -> bool:
    if any(ch in pattern for ch in "*?[]"):
        return any(path.glob(pattern))
    return (path / pattern).is_file()


def _is_sidecar_safetensors(name: str) -> bool:
    """True for pi05/lerobot processor sidecars, not main model weights."""
    lower = name.lower()
    return any(
        token in lower
        for token in ("normalizer", "unnormalizer", "processor", "preprocessor", "postprocessor")
    )


def _has_main_safetensors(path: Path) -> bool:
    return any(
        entry.is_file() and not _is_sidecar_safetensors(entry.name)
        for entry in path.glob("*.safetensors")
    )


def has_checkpoint_weight_files(path: Path) -> bool:
    for name in _CHECKPOINT_WEIGHT_FILES:
        if (path / name).is_file():
            return True
    if (path / "config.json").is_file() and _has_main_safetensors(path):
        return True
    if (path / "mtp.safetensors").is_file():
        return True
    if any(path.glob("*.ckpt")):
        return True
    return False


def has_usable_checkpoint(path: Path, *, require_norm_stats: bool = False) -> bool:
    """True when *path* contains loadable weights (and norm stats when required)."""
    if not path.is_dir():
        return False
    if not has_checkpoint_weight_files(path):
        return False
    if require_norm_stats and not has_norm_stats_sources(path):
        return False
    return True


def has_cached_weight_files(
    path: Path,
    allow_patterns: list[str] | None = None,
    *,
    require_norm_stats: bool = False,
) -> bool:
    """True when *path* already contains the requested weight files."""
    if not path.is_dir():
        return False
    if has_usable_checkpoint(path, require_norm_stats=require_norm_stats):
        return True
    if not allow_patterns:
        return False
    return all(_matches_allow_pattern(path, pat) for pat in allow_patterns)
