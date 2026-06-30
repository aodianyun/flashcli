"""Tests for runtime env key resolution."""

from __future__ import annotations

from flashcli.bundle.runtime_env import parse_variant_key, resolve_runtime_env_key


def test_parse_generic_platform_tail() -> None:
    key = parse_variant_key("gfx942-rocm611-linux-x86_64-py312")
    assert key.platform_tail == "gfx942-rocm611"
    assert key.sm is None
    assert key.cuda_tag is None
    assert key.catalog_name() == "gfx942-rocm611-linux-x86_64-py312"


def test_resolve_runtime_exact() -> None:
    runtime = {
        "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
    }
    key = "sm89-cu124-linux-x86_64-py312"
    assert resolve_runtime_env_key(runtime, key) == key


def test_resolve_runtime_fuzzy_sm() -> None:
    runtime = {
        "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312",
    }
    host = "sm120-cu130-linux-x86_64-py312"
    assert resolve_runtime_env_key(runtime, host) == "sm89-cu130-linux-x86_64-py312"
