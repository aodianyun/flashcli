"""Bootstrap ``flashcli_bundle`` imports without installing flashcli."""

from __future__ import annotations

import sys
from pathlib import Path


def flashcli_root_from_here(*, here: Path | None = None) -> Path:
    """Return flashcli package root (parent of ``scripts/``)."""
    anchor = here or Path(__file__).resolve()
    return anchor.parents[2] if anchor.name.endswith(".py") else anchor


def ensure_flashcli_bundle_on_path(
    flashcli_root: Path | None = None,
) -> Path:
    """Insert ``flashcli-bundle/src`` on ``sys.path``; return that directory."""
    root = (flashcli_root or flashcli_root_from_here(here=Path(__file__))).resolve()
    bundle_src = root / "flashcli-bundle" / "src"
    if not bundle_src.is_dir():
        raise SystemExit(f"flashcli-bundle src not found: {bundle_src}")
    text = str(bundle_src)
    if text not in sys.path:
        sys.path.insert(0, text)
    return bundle_src
