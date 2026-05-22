"""Checkpoint directory detection (shared by weights download and bundle resolve)."""

from __future__ import annotations

from pathlib import Path

_CHECKPOINT_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.bin",
)


def has_usable_checkpoint(path: Path) -> bool:
    """True when *path* contains weights flashcli can load (not HF hub metadata only)."""
    if not path.is_dir():
        return False
    for name in _CHECKPOINT_WEIGHT_FILES:
        if (path / name).is_file():
            return True
    if (path / "config.json").is_file() and any(path.glob("*.safetensors")):
        return True
    return False
