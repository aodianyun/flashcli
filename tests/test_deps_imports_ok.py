"""Tests for pip spec satisfaction in deps._imports_ok."""

from __future__ import annotations

import subprocess
import sys

from flashcli.deps import _imports_ok


def test_imports_ok_rejects_huggingface_hub_1x_for_transformers_compat() -> None:
    """transformers<4.56 needs huggingface-hub<1.0; 1.x must not count as satisfied."""
    spec = "huggingface_hub>=0.26,<1.0"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "show",
            "huggingface-hub",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return  # skip when hub not installed in test env
    version_line = next(
        (ln.split(":", 1)[1].strip() for ln in proc.stdout.splitlines() if ln.startswith("Version:")),
        "",
    )
    if not version_line.startswith("1."):
        return
    assert _imports_ok(spec) is False
