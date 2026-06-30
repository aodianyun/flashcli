from __future__ import annotations

from flashcli.bundle.native_naming import (
    logical_native_module_name,
    native_artifact_tag,
    native_so_filename,
    parse_native_artifact,
    parse_native_tag_suffix,
    sanitize_flashrt_abi,
)


def test_tag_and_filename():
    abi = sanitize_flashrt_abi("v1.2.3+gpu", git_commit="abcdef012345")
    tag = native_artifact_tag(
        flashrt_abi=abi,
        sm="89",
        cuda_tag="124",
        os_name="linux",
        arch="x86_64",
        python_minor="312",
    )
    assert tag == f"{abi}-sm89-cu124-linux-x86_64-py312"
    assert (
        native_so_filename("flash_rt_kernels", tag)
        == f"flash_rt_kernels-{tag}.so"
    )


def test_logical_module_name():
    name = "flash_rt_kernels-dev-sm89-cu124-linux-x86_64-py312.so"
    assert logical_native_module_name(name) == "flash_rt_kernels"
    assert logical_native_module_name("flash_rt_fa2.so") == "flash_rt_fa2"
    vlk = "flash_rt_qwen3_vl_kernels-dev-sm120-cu130-linux-x86_64-py312.so"
    assert logical_native_module_name(vlk) == "flash_rt_qwen3_vl_kernels"


def test_parse_native_artifact_env_key_anchored():
    env_key = "sm120-cu130-linux-x86_64-py312"
    parsed = parse_native_artifact(
        f"flash_rt_omnivoice-1.0.0-{env_key}.so",
        env_key=env_key,
    )
    assert parsed is not None
    assert parsed.module_base == "flash_rt_omnivoice"
    assert parsed.flashrt_abi == "1.0.0"
    assert parsed.catalog_key() == env_key


def test_parse_native_artifact_generic_platform_tail():
    env_key = "gfx942-rocm611-linux-x86_64-py312"
    parsed = parse_native_artifact(
        f"flash_rt_kernels-dev-{env_key}.so",
        env_key=env_key,
    )
    assert parsed is not None
    assert parsed.sm is None
    assert parsed.cuda_tag is None
    assert parsed.catalog_key() == env_key
