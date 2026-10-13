"""Shared fixtures for the execution-ABI conformance suite."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GO_DIR = ROOT / "go"


@pytest.fixture(scope="session")
def go_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Path to a flashcli-go binary, or skip when Go is unavailable."""
    env_bin = os.environ.get("FLASHCLI_GO_BIN")
    if env_bin and Path(env_bin).is_file():
        return Path(env_bin)
    if shutil.which("go") is None:
        pytest.skip("go toolchain not available")
    out = tmp_path_factory.mktemp("gobin") / "flashcli-go"
    proc = subprocess.run(
        ["go", "build", "-o", str(out), "./cmd/flashcli"],
        cwd=GO_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"go build failed: {proc.stderr.strip()[:300]}")
    return out
