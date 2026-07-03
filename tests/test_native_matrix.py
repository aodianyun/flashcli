from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.bundle.manifest import load_bundle_manifest
from flashcli.bundle.native import probe_native_python_abi
from flashcli.bundle.native_naming import (
    NativeEnvironmentNotSupportedError,
    ParsedNativeTag,
    host_runtime_env_key,
    native_dir_has_tagged_native_artifacts,
    native_so_filename,
    parse_native_tag_suffix,
    resolve_native_modules_for_host,
    score_native_tag,
)
from flashcli.runtime.detect import GpuInfo

CELL312 = "sm89-cu124-linux-x86_64-py312"
CELL310 = "sm89-cu124-linux-x86_64-py310"
RUNTIME312 = f"runtime/{CELL312}"


def _gpu(sm: str = "89", cuda: str = "124") -> GpuInfo:
    return GpuInfo(
        sm=sm,
        cuda_tag=cuda,
        os_name="linux",
        arch="x86_64",
        recommended_torch_index="cu124",
        gpu_name="Test",
    )


def _runtime_dir(root: Path, cell: str) -> Path:
    d = root / "runtime" / cell
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_parse_tag_suffix():
    t = parse_native_tag_suffix("abc-sm89-cu124-linux-x86_64-py312")
    assert t is not None
    assert t.sm == "89"
    assert t.python_minor == "312"


def test_select_kernels_only(tmp_path: Path) -> None:
    native = _runtime_dir(tmp_path, CELL312)
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    (native / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    resolved = resolve_native_modules_for_host(
        tmp_path,
        _gpu(),
        native_dir_rel=RUNTIME312,
        python_minor="312",
    )
    assert set(resolved) == {"flash_rt_kernels"}


def test_select_from_runtime(tmp_path: Path):
    native = _runtime_dir(tmp_path, CELL312)
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (native / native_so_filename(base, tag)).write_bytes(b"\x00")
    tag310 = "dev-sm89-cu124-linux-x86_64-py310"
    other = _runtime_dir(tmp_path, CELL310)
    (other / native_so_filename("flash_rt_kernels", tag310)).write_bytes(b"\x00")

    resolved = resolve_native_modules_for_host(
        tmp_path,
        _gpu(),
        native_dir_rel=RUNTIME312,
        allowed_sm=["89", "120"],
        python_minor="312",
    )
    assert resolved["flash_rt_kernels"].parent.name == CELL312
    assert resolved["flash_rt_kernels"].name.endswith("py312.so")


def test_select_missing_fails(tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    tag = "dev-sm89-cu130-linux-x86_64-py310"
    (lib / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    with pytest.raises(NativeEnvironmentNotSupportedError):
        resolve_native_modules_for_host(
            tmp_path,
            _gpu(cuda="124"),
            native_lib_rel="lib",
            python_minor="310",
        )


def test_select_cu130_when_host_cuda_130(tmp_path: Path) -> None:
    for cuda in ("124", "130"):
        cell = f"sm89-cu{cuda}-linux-x86_64-py310"
        native = _runtime_dir(tmp_path, cell)
        tag = f"dev-sm89-cu{cuda}-linux-x86_64-py310"
        for base in ("flash_rt_kernels", "flash_rt_fa2"):
            (native / native_so_filename(base, tag)).write_bytes(b"\x00")
    resolved = resolve_native_modules_for_host(
        tmp_path,
        _gpu(cuda="130"),
        native_dir_rel="runtime/sm89-cu130-linux-x86_64-py310",
        python_minor="310",
    )
    assert "cu130" in resolved["flash_rt_kernels"].name
    assert "cu130" in resolved["flash_rt_fa2"].name


def test_native_dir_has_tagged_native_artifacts(tmp_path: Path) -> None:
    native = _runtime_dir(tmp_path, "sm120-cu130-linux-x86_64-py312")
    assert not native_dir_has_tagged_native_artifacts(native)
    (native / native_so_filename("flash_rt_kernels", "dev-sm120-cu130-linux-x86_64-py312")).write_bytes(
        b"\x00"
    )
    assert native_dir_has_tagged_native_artifacts(native)


def _v3_bundle(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "flash_rt").mkdir()
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    cell = "sm120-cu130-linux-x86_64-py312"
    native = _runtime_dir(root, cell)
    tag = f"dev-{cell}"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (native / native_so_filename(base, tag)).write_bytes(b"\x00")
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "qwen_nvfp4",
        "python_abi": "312",
        "runtime": {cell: f"runtime/{cell}"},
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "python_dependencies": {"torch": {"package": "torch", "index": "cu124"}, "pip": []},
    }
    (root / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")


@patch("flashcli_bundle.native._probe_so_file")
def test_probe_uses_manifest_python_abi(mock_probe, tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _v3_bundle(root)
    bundle = load_bundle_manifest(root)
    probe_native_python_abi(bundle, gpu=_gpu(sm="120", cuda="130"))
    mock_probe.assert_called()
    assert mock_probe.call_args[0][0].name.endswith("py312.so")


@patch("flashcli_bundle.native_validate.probe_native_so_abi", return_value=None)
def test_probe_so_file_uses_tagged_python_when_host_minor_differs(
    mock_probe, tmp_path: Path
) -> None:
    from flashcli_bundle.native import _probe_so_file
    from flashcli_bundle.native_naming import native_so_filename

    cell = "sm120-cu130-linux-x86_64-py310"
    so = tmp_path / native_so_filename("flash_rt_fa2", f"dev-{cell}")
    so.write_bytes(b"\x7fELF")
    _probe_so_file(so, env_key=cell, python_minor="310")
    mock_probe.assert_called_once()
    assert mock_probe.call_args.kwargs["python_minor"] == "310"


def test_sm120_uses_sm89_artifact(tmp_path: Path):
    native = _runtime_dir(tmp_path, CELL312)
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    (native / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    (native / native_so_filename("flash_rt_fa2", tag)).write_bytes(b"\x00")
    host = host_runtime_env_key(_gpu(sm="120", cuda="128"), python_minor="312")
    artifact = ParsedNativeTag.from_parts(
        module_base="flash_rt_kernels",
        flashrt_abi="dev",
        env_key=CELL312,
    )
    assert score_native_tag(artifact, host, allowed_sm=["89", "120"]) > 0


def test_load_omnivoice_from_runtime_cell(tmp_path: Path) -> None:
    cell = CELL312
    native = _runtime_dir(tmp_path, cell)
    tag = f"1.0.0-{cell}"
    (native / native_so_filename("flash_rt_omnivoice", tag)).write_bytes(b"\x00")
    resolved = resolve_native_modules_for_host(
        tmp_path,
        _gpu(),
        native_dir_rel=RUNTIME312,
        python_minor="312",
    )
    assert set(resolved) == {"flash_rt_omnivoice"}
