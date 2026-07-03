"""Bundle build Python resolution (scripts/lib/bundle_build_python.sh)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "lib" / "bundle_build_python.sh"
GROOT_N17 = ROOT / "bundles" / "groot_n17"


def _bash(expr: str) -> str:
    proc = subprocess.run(
        ["bash", "-c", expr],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def test_bundle_manifest_python_abi_reads_groot_n17() -> None:
    abi = _bash(
        f"source '{LIB}' && bundle_manifest_python_abi '{GROOT_N17}'"
    )
    assert abi == "310"


def test_groot_n17_build_script_sources_bundle_build_python() -> None:
    build_sh = GROOT_N17 / "_bundle_build.sh"
    text = build_sh.read_text(encoding="utf-8")
    assert "bundle_build_python.sh" in text
    assert "bundle_build_python_prepare" in text
    assert "cmake_python.sh" in text
    assert "cmake_append_python3_args" in text
    assert "--no-install-python" in text
