"""Checkpoint directory detection (shared by weights download and bundle resolve)."""

from __future__ import annotations

from pathlib import Path

_CHECKPOINT_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.bin",
)


def _matches_allow_pattern(path: Path, pattern: str) -> bool:
    if any(ch in pattern for ch in "*?[]"):
        return any(path.glob(pattern))
    return (path / pattern).is_file()


def has_cached_weight_files(
    path: Path,
    allow_patterns: list[str] | None = None,
) -> bool:
    """True when *path* already contains the requested weight files."""
    if not path.is_dir():
        return False
    if has_usable_checkpoint(path):
        return True
    if not allow_patterns:
        return False
    return all(_matches_allow_pattern(path, pat) for pat in allow_patterns)


def has_usable_checkpoint(path: Path) -> bool:
    """True when *path* contains weights flashcli can load (not HF hub metadata only)."""
    if not path.is_dir():
        return False
    for name in _CHECKPOINT_WEIGHT_FILES:
        if (path / name).is_file():
            return True
    if (path / "config.json").is_file() and any(path.glob("*.safetensors")):
        return True
    # Single-file extras (e.g. qwen36 MTP: mtp.safetensors only).
    if (path / "mtp.safetensors").is_file():
        return True
    return False
