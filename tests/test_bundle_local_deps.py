"""Bundle-local python_dependencies (shipped on PYTHONPATH, not PyPI)."""

from __future__ import annotations

import sys
from pathlib import Path

from flashcli_bundle.runtime.requirements_spec import (
    bundle_provides_module,
    requirement_import_satisfied,
    requirement_needs_pip_install,
)


def test_bundle_provides_module_detects_package_dir(tmp_path: Path) -> None:
    pkg = tmp_path / "melband_roformer_infer"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    assert bundle_provides_module(tmp_path, "melband_roformer_infer")
    assert not requirement_needs_pip_install(
        "melband_roformer_infer",
        python=sys.executable,
        bundle_root=tmp_path,
    )


def test_requirement_import_satisfied_with_bundle_root(tmp_path: Path) -> None:
    pkg = tmp_path / "melband_roformer_infer"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("MARKER = 1\n", encoding="utf-8")
    assert requirement_import_satisfied(
        "melband_roformer_infer",
        python=sys.executable,
        bundle_root=tmp_path,
    )
