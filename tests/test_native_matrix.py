from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.bundle.manifest import load_bundle_manifest
from flashcli.bundle.native import _native_matrix_enabled, probe_native_python_abi
from flashcli.bundle.native_naming import (
    NativeEnvironmentNotSupportedError,
    ParsedNativeTag,
    lib_dir_has_tagged_native_artifacts,
    native_so_filename,
    parse_native_tag_suffix,
    resolve_native_modules_for_host,
    score_native_tag,
)
from flashcli.bundle.native_naming import host_runtime_env_key
from flashcli.runtime.detect import GpuInfo


def _gpu(sm: str = "89", cuda: str = "124") -> GpuInfo:
    return GpuInfo(
        sm=sm,
        cuda_tag=cuda,
        os_name="linux",
        arch="x86_64",
        recommended_torch_index="cu124",
        gpu_name="Test",
    )


def test_parse_tag_suffix():
    t = parse_native_tag_suffix("abc-sm89-cu124-linux-x86_64-py312")
    assert t is not None
    assert t.sm == "89"
    assert t.python_minor == "312"


def test_select_from_lib(tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    for base in ("flash_rt_kernels", "flash_rt_fa2"):
        (lib / native_so_filename(base, tag)).write_bytes(b"\x00")
    tag310 = "dev-sm89-cu124-linux-x86_64-py310"
    (lib / native_so_filename("flash_rt_kernels", tag310)).write_bytes(b"\x00")
    (lib / native_so_filename("flash_rt_fa2", tag310)).write_bytes(b"\x00")

    resolved = resolve_native_modules_for_host(
        tmp_path,
        _gpu(),
        allowed_sm=["89", "120"],
        python_minor="312",
    )
    assert resolved["flash_rt_kernels"].parent.name == "lib"
    assert resolved["flash_rt_kernels"].name.endswith("py312.so")


def test_select_missing_fails(tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    tag = "dev-sm89-cu130-linux-x86_64-py310"
    (lib / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    with pytest.raises(NativeEnvironmentNotSupportedError):
        resolve_native_modules_for_host(tmp_path, _gpu(cuda="124"))


def test_select_cu130_when_host_cuda_130(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    for cuda in ("124", "130"):
        tag = f"dev-sm89-cu{cuda}-linux-x86_64-py310"
        for base in ("flash_rt_kernels", "flash_rt_fa2"):
            (lib / native_so_filename(base, tag)).write_bytes(b"\x00")
    resolved = resolve_native_modules_for_host(
        tmp_path, _gpu(cuda="130"), python_minor="310"
    )
    assert "cu130" in resolved["flash_rt_kernels"].name
    assert "cu130" in resolved["flash_rt_fa2"].name


def test_lib_dir_has_tagged_native_artifacts(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    assert not lib_dir_has_tagged_native_artifacts(lib)
    (lib / native_so_filename("flash_rt_kernels", "dev-sm120-cu130-linux-x86_64-py312")).write_bytes(
        b"\x00"
    )
    assert lib_dir_has_tagged_native_artifacts(lib)


def _bundle_without_matrix_manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "lib").mkdir()
    (root / "flash_rt").mkdir()
    (root / "run.py").write_text("# stub\n", encoding="utf-8")
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 2,
        "name": "qwen_nvfp4",
        "capabilities": ["run"],
        "entry": {"run": {"module": "run", "attr": "RunEngine"}},
        "python_dependencies": {"torch": "torch", "pip": []},
        "requires": {"sm": ["120"]},
        "weights": {"source": "huggingface", "repo": "test/model"},
    }
    (root / "flashcli-bundle.json").write_text(json.dumps(data), encoding="utf-8")


def test_native_matrix_auto_detect_without_manifest(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _bundle_without_matrix_manifest(root)
    lib = root / "lib"
    for py in ("310", "311", "312"):
        tag = f"dev-sm120-cu130-linux-x86_64-py{py}"
        for base in ("flash_rt_kernels", "flash_rt_fa2"):
            (lib / native_so_filename(base, tag)).write_bytes(b"\x00")
    bundle = load_bundle_manifest(root)
    assert _native_matrix_enabled(bundle)


@patch("flashcli.bundle.native_naming.host_python_minor", return_value="312")
@patch("flashcli.bundle.native._probe_so_file")
def test_probe_selects_host_python_abi_without_manifest(
    mock_probe, _mock_py, tmp_path: Path
) -> None:
    root = tmp_path / "bundle"
    _bundle_without_matrix_manifest(root)
    lib = root / "lib"
    for py in ("310", "311", "312"):
        tag = f"dev-sm120-cu130-linux-x86_64-py{py}"
        for base in ("flash_rt_kernels", "flash_rt_fa2"):
            (lib / native_so_filename(base, tag)).write_bytes(b"\x00")
    bundle = load_bundle_manifest(root)
    probe_native_python_abi(bundle, gpu=_gpu(sm="120", cuda="130"))
    mock_probe.assert_called_once()
    assert mock_probe.call_args[0][0].name.endswith("py312.so")


def test_sm120_uses_sm89_artifact(tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    (lib / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    (lib / native_so_filename("flash_rt_fa2", tag)).write_bytes(b"\x00")
    host = host_runtime_env_key(_gpu(sm="120", cuda="128"), python_minor="312")
    artifact = ParsedNativeTag("dev", "89", "124", "linux", "x86_64", "312")
    assert score_native_tag(artifact, host, allowed_sm=["89", "120"]) > 0
