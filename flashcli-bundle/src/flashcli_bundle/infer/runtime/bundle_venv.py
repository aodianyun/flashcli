"""Bundle venv helpers for infer runtime (read-only; venv created on host)."""

from __future__ import annotations

import os
from pathlib import Path

from flashcli_bundle.infer.bundle.marker import runtime_dir


def venv_path(runtime_id: str) -> Path:
    return runtime_dir(runtime_id) / "venv"


def venv_python(runtime_id: str) -> Path:
    root = venv_path(runtime_id)
    for name in ("python3", "python"):
        candidate = root / "bin" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No python in bundle venv: {root}")


def in_bundle_venv(runtime_id: str | None = None) -> bool:
    want = runtime_id or os.environ.get("FLASHCLI_RUNTIME_ID", "")
    if os.environ.get("FLASHCLI_IN_BUNDLE_VENV") != "1":
        return False
    if want and os.environ.get("FLASHCLI_RUNTIME_ID") != want:
        return False
    return True
