from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.bundle.manifest import BundleManifest, load_bundle_manifest, validate_bundle_layout
from flashcli.bundle.native_naming import native_so_filename
from flashcli.bundle.native_validate import (
    validate_native_runtime_abi,
    validate_native_runtime_matrix,
)


def _write_runtime_cell(root: Path, cell: str) -> Path:
    native = root / "runtime" / cell
    native.mkdir(parents=True, exist_ok=True)
    tag = f"dev-{cell}"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (native / native_so_filename(base, tag)).write_bytes(b"\x7fELF")
    return native


def _write_bundle(
    root: Path,
    *,
    native_cells: list[str] | None = None,
) -> BundleManifest:
    root.mkdir(parents=True, exist_ok=True)
    (root / "flash_rt").mkdir()
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    cells = native_cells or []
    native_art = {cell: f"runtime/{cell}" for cell in cells}
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "test_bundle",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "run_options": [
            {
                "name": "prompt",
                "type": "string",
                "default": "",
                "help": "Prompt text.",
                "phase": "predict",
            }
        ],
        "python_dependencies": {"torch": {"package": "torch", "index": "cu124"}, "pip": []},
        "weights": {"source": "huggingface", "repo": "org/model", "revision": "main"},
        "runtime": native_art,
    }
    (root / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")
    return load_bundle_manifest(root)


def test_matrix_missing_cell(tmp_path: Path) -> None:
    root = tmp_path / "b"
    bundle = _write_bundle(
        root,
        native_cells=[
            "sm120-cu130-linux-x86_64-py312",
            "sm120-cu130-linux-x86_64-py311",
        ],
    )
    _write_runtime_cell(root, "sm120-cu130-linux-x86_64-py312")
    errs = validate_native_runtime_matrix(bundle)
    assert any("py311" in e for e in errs)
    assert any("missing runtime/sm120-cu130-linux-x86_64-py311" in e for e in errs)


def test_validate_bundle_layout_env_key_skips_other_cells(tmp_path: Path) -> None:
    root = tmp_path / "b"
    present = "sm89-cu124-linux-x86_64-py312"
    missing = "sm89-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[present, missing])
    _write_runtime_cell(root, present)
    errs = validate_bundle_layout(bundle, env_key=present)
    assert not errs
    errs_all = validate_bundle_layout(bundle)
    assert any(missing in e for e in errs_all)


def test_matrix_inconsistent_python_tag(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[cell])
    native = root / "runtime" / cell
    native.mkdir(parents=True)
    (native / native_so_filename("flash_rt_kernels", f"dev-{cell}")).write_bytes(b"\x7fELF")
    (native / native_so_filename("flash_rt_fa2", "dev-sm120-cu130-linux-x86_64-py310")).write_bytes(
        b"\x7fELF"
    )
    errs = validate_native_runtime_matrix(bundle)
    assert any("does not match runtime cell" in e or "inconsistent python_abi" in e for e in errs)


@patch("flashcli_bundle.native_validate.probe_native_so_abi", return_value=None)
def test_validate_bundle_layout_calls_abi_probe(mock_probe, tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[cell])
    _write_runtime_cell(root, cell)
    errs = validate_bundle_layout(bundle, probe_abi=True)
    assert not errs
    assert mock_probe.called


def test_abi_probe_invoked_per_module(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[cell])
    _write_runtime_cell(root, cell)
    with patch(
        "flashcli_bundle.native_validate.probe_native_so_abi", return_value=None
    ) as mock_probe:
        validate_native_runtime_abi(bundle)
        assert mock_probe.call_count >= 2


def test_kernels_only_runtime_cell_passes(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[cell])
    native = root / "runtime" / cell
    native.mkdir(parents=True)
    (native / native_so_filename("flash_rt_kernels", f"dev-{cell}")).write_bytes(b"\x7fELF")
    errs = validate_native_runtime_matrix(bundle)
    assert not errs


def test_empty_runtime_cell_fails(tmp_path: Path) -> None:
    root = tmp_path / "b"
    cell = "sm120-cu130-linux-x86_64-py312"
    bundle = _write_bundle(root, native_cells=[cell])
    (root / "runtime" / cell).mkdir(parents=True)
    errs = validate_native_runtime_matrix(bundle)
    assert any("no recognized native" in e for e in errs)
