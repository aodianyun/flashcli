"""Tests for pip spec satisfaction in deps._imports_ok."""

from __future__ import annotations

import subprocess
import sys

from flashcli.deps import FLASHCLI_HOST_PACKAGES, _imports_ok


def test_host_packages_include_huggingface_hub() -> None:
    assert any("huggingface_hub" in p for p in FLASHCLI_HOST_PACKAGES)


def test_host_packages_exclude_bundle_stack_pins() -> None:
    joined = " ".join(FLASHCLI_HOST_PACKAGES).lower()
    assert "transformers" not in joined
    assert "torch" not in joined


def test_imports_ok_accepts_huggingface_hub_1x_on_host() -> None:
    """Host CLI allows huggingface-hub 1.x (independent from bundle transformers)."""
    spec = "huggingface_hub>=0.26"
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "show", "huggingface-hub"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return  # skip when hub not installed in test env
    version_line = next(
        (
            ln.split(":", 1)[1].strip()
            for ln in proc.stdout.splitlines()
            if ln.startswith("Version:")
        ),
        "",
    )
    if not version_line.startswith("1."):
        return
    assert _imports_ok(spec) is True
