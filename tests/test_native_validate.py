from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, validate_bundle_layout
from flashcli.bundle.native_naming import native_so_filename
from flashcli.bundle.native_validate import (
    validate_native_lib_abi,
    validate_native_lib_matrix,
)


def _write_bundle(
    root: Path,
    *,
    native_matrix: list[str] | None = None,
    sm: list[str] | None = None,
) -> BundleManifest:
    root.mkdir(parents=True, exist_ok=True)
    lib = root / "lib"
    lib.mkdir()
    (root / "flash_rt").mkdir()
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 2,
        "name": "test_bundle",
        "capabilities": ["run"],
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "python_dependencies": {"torch": "torch", "pip": [], "optional_groups": {}},
        "native_layout": "matrix" if native_matrix else None,
        "native_matrix": native_matrix or [],
        "requires": {"sm": sm or ["120"]},
        "weights": {"source": "huggingface", "repo": "test/model"},
    }
    (root / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")
    return load_bundle_manifest(root)


def test_matrix_missing_cell(tmp_path: Path) -> None:
    root = tmp_path / "b"
    bundle = _write_bundle(
        root,
        native_matrix=[
            "sm120-cu130-linux-x86_64-py310",
            "sm120-cu130-linux-x86_64-py311",
        ],
    )
    tag = "dev-sm120-cu130-linux-x86_64-py310"
    lib = root / "lib"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (lib / native_so_filename(base, tag)).write_bytes(b"\x7fELF")
    errs = validate_native_lib_matrix(bundle)
    assert any("py311" in e for e in errs)
    assert any("missing lib/flash_rt_kernels" in e for e in errs)


def test_matrix_inconsistent_python_tag(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py310"
    bundle = _write_bundle(root, native_matrix=[cell])
    lib = root / "lib"
    (lib / native_so_filename("flash_rt_kernels", f"dev-{cell}")).write_bytes(b"\x7fELF")
    (lib / native_so_filename("flash_rt_fa2", "dev-sm120-cu130-linux-x86_64-py312")).write_bytes(
        b"\x7fELF"
    )
    errs = validate_native_lib_matrix(bundle)
    assert any("inconsistent python_abi" in e for e in errs)


@patch("flashcli.bundle.native_validate.probe_native_so_abi", return_value=None)
def test_validate_bundle_layout_calls_abi_probe(mock_probe, tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py310"
    bundle = _write_bundle(root, native_matrix=[cell])
    lib = root / "lib"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (lib / native_so_filename(base, f"dev-{cell}")).write_bytes(b"\x7fELF")
    errs = validate_bundle_layout(bundle, probe_abi=True)  # same as CLI default
    assert errs == []
    assert mock_probe.call_count == 2


def test_abi_probe_reports_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py310"
    bundle = _write_bundle(root, native_matrix=[cell])
    so = root / "lib" / native_so_filename("flash_rt_kernels", f"dev-{cell}")
    so.write_bytes(b"\x7fELF")

    with patch(
        "flashcli.bundle.native_validate.probe_native_so_abi",
        return_value="flash_rt_kernels-...: Python ABI does not match",
    ):
        errs = validate_native_lib_abi(bundle)
    assert len(errs) == 1
    assert "ABI" in errs[0]
