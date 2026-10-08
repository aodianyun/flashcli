"""M6 gate: the Go release build injects the pyproject version and checksums.

Skipped when the Go toolchain or bash is unavailable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match
    return match.group(1)


def test_build_go_injects_version(tmp_path: Path) -> None:
    if shutil.which("go") is None or shutil.which("bash") is None:
        pytest.skip("go toolchain or bash not available")
    out = tmp_path / "dist"
    env = dict(os.environ, FLASHCLI_GO_TARGETS="linux/amd64")
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "build_go.sh"), str(out)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr

    binary = out / "flashcli-linux-amd64"
    sums = out / "sha256sums.txt"
    assert binary.is_file()
    assert sums.is_file()
    assert "flashcli-linux-amd64" in sums.read_text(encoding="utf-8")

    version = subprocess.run([str(binary), "version"], capture_output=True, text=True)
    assert version.stdout.strip() == _pyproject_version()


def test_installer_scripts_syntax() -> None:
    if shutil.which("sh") is None:
        pytest.skip("sh not available")
    for script in ["install.sh", "scripts/install_go.sh", "scripts/build_go.sh", "scripts/release_go.sh"]:
        proc = subprocess.run(["sh", "-n", str(ROOT / script)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{script}: {proc.stderr}"
    for script in ["scripts/build_go.sh", "scripts/release_go.sh"]:
        if shutil.which("bash"):
            proc = subprocess.run(["bash", "-n", str(ROOT / script)], capture_output=True, text=True)
            assert proc.returncode == 0, f"{script}: {proc.stderr}"


def test_install_sh_delegates_to_go(tmp_path: Path) -> None:
    if shutil.which("sh") is None:
        pytest.skip("sh not available")
    fake = tmp_path / "fake_install_go.sh"
    fake.write_text("#!/bin/sh\necho \"GO-INSTALLER args=$*\"\nexit 0\n", encoding="utf-8")
    env = dict(os.environ, FLASHCLI_GO_SCRIPT_URL=f"file://{fake}")
    proc = subprocess.run(
        ["sh", str(ROOT / "install.sh"), "--mirror"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "GO-INSTALLER args=--mirror" in proc.stdout

