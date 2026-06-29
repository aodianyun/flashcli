"""Pip requirement satisfaction for bundle venv (PyPI name vs import name)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flashcli_bundle.runtime.requirements_spec import (
    import_name_for_requirement,
    requirement_import_satisfied,
)


def test_melband_pypi_import_name() -> None:
    assert import_name_for_requirement("melband-roformer-infer==0.1.1") == "mel_band_roformer"


def test_requirement_satisfied_by_distribution_metadata(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "-q", "packaging>=23.0"], check=True)
    assert requirement_import_satisfied("packaging>=23.0", python=py)


def test_requirement_unsatisfied_when_version_below_specifier(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "-q", "packaging==23.2"], check=True)
    assert not requirement_import_satisfied("packaging>=24.0", python=py)
