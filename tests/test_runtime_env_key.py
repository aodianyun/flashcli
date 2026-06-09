"""Tests for runtime env key resolution."""

from __future__ import annotations

from flashcli.bundle.runtime_env import resolve_runtime_env_key


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
