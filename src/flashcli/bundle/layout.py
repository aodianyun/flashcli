"""Bundle root detection."""

from __future__ import annotations

from pathlib import Path


def is_bundle_root(path: Path) -> bool:
    return path.is_dir() and (path / "flashcli-bundle.json").is_file()
