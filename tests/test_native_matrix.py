from __future__ import annotations

from pathlib import Path

import pytest

from flashcli.bundle.native_naming import (
    NativeEnvironmentNotSupportedError,
    ParsedNativeTag,
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


def test_sm120_uses_sm89_artifact(tmp_path: Path):
    lib = tmp_path / "lib"
    lib.mkdir()
    tag = "dev-sm89-cu124-linux-x86_64-py312"
    (lib / native_so_filename("flash_rt_kernels", tag)).write_bytes(b"\x00")
    (lib / native_so_filename("flash_rt_fa2", tag)).write_bytes(b"\x00")
    host = host_runtime_env_key(_gpu(sm="120", cuda="128"), python_minor="312")
    artifact = ParsedNativeTag("dev", "89", "124", "linux", "x86_64", "312")
    assert score_native_tag(artifact, host, allowed_sm=["89", "120"]) > 0
