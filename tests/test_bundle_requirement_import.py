"""Pip requirement satisfaction for bundle venv (PyPI name vs import name)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flashcli_bundle.runtime.requirements_spec import (
    import_name_for_requirement,
    requirement_import_failure_reason,
    requirement_import_satisfied,
)


def test_melband_pypi_import_name() -> None:
    assert import_name_for_requirement("melband-roformer-infer==0.1.1") == "mel_band_roformer"


def test_dm_tree_import_name() -> None:
    assert import_name_for_requirement("dm-tree") == "tree"


def test_opencv_headless_import_name() -> None:
    assert import_name_for_requirement("opencv-python-headless>=4.5,<4.13") == "cv2"


def test_opencv_contrib_import_name() -> None:
    assert import_name_for_requirement("opencv-contrib-python") == "cv2"


def test_requirement_satisfied_dm_tree_when_installed(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "-q", "dm-tree"], check=True)
    assert requirement_import_satisfied("dm-tree", python=py)


def test_requirement_satisfied_opencv_headless_when_installed(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "opencv-python-headless==4.10.0.84"],
        check=True,
    )
    assert requirement_import_satisfied("opencv-python-headless>=4.5,<4.13", python=py)


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


def test_requirement_unsatisfied_when_metadata_ok_but_import_missing(tmp_path: Path) -> None:
    """Metadata alone must not satisfy a spec (guards broken/partial installs)."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    site = py.parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    dist = site / "click-8.1.8.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: click\nVersion: 8.1.8\n",
        encoding="utf-8",
    )
    assert not requirement_import_satisfied("click==8.1.8", python=py)


def test_requirement_satisfied_when_bundle_root_shadows_pypi_name(
    tmp_path: Path,
) -> None:
    """Import probe must not prepend bundle_root (shadows paddleocr/cv2 on PYTHONPATH)."""
    venv = tmp_path / "venv"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "paddleocr==3.7.0", "opencv-contrib-python==4.10.0.84"],
        check=True,
    )
    (bundle / "paddleocr.py").write_text("raise ImportError('shadow')\n", encoding="utf-8")
    (bundle / "cv2.py").write_text("raise ImportError('shadow')\n", encoding="utf-8")
    assert requirement_import_satisfied(
        "paddleocr==3.7.0", python=py, bundle_root=bundle
    )
    assert requirement_import_satisfied(
        "opencv-contrib-python", python=py, bundle_root=bundle
    )


def test_requirement_satisfied_when_module_init_would_fail_at_runtime(
    tmp_path: Path,
) -> None:
    """find_spec verifies pip layout; runtime import may still fail later in infer."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    site = (
        py.parent.parent
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    pkg = site / "brokenpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise RuntimeError('gpu missing')\n", encoding="utf-8")
    dist = site / "brokenpkg-1.0.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: brokenpkg\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (dist / "top_level.txt").write_text("brokenpkg\n", encoding="utf-8")
    assert requirement_import_satisfied("brokenpkg==1.0.0", python=py)


def test_requirement_failure_reason_reports_missing_distribution(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    reason = requirement_import_failure_reason("not-installed-pkg==1.0.0", python=py)
    assert reason is not None
    assert "not installed" in reason


def test_requirement_satisfied_ignores_host_pythonpath_shadow(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "-q", "paddleocr==3.7.0", "opencv-contrib-python==4.10.0.84"],
        check=True,
    )
    (shadow / "paddleocr.py").write_text("raise ImportError('shadow')\n", encoding="utf-8")
    (shadow / "cv2.py").write_text("raise ImportError('shadow')\n", encoding="utf-8")
    import os

    prev = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(shadow)
    try:
        assert requirement_import_satisfied("paddleocr==3.7.0", python=py)
        assert requirement_import_satisfied("opencv-contrib-python", python=py)
    finally:
        if prev is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prev
