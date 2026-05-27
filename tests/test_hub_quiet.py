"""Tests for HF download log suppression helpers."""

from __future__ import annotations

from flashcli.util.hub_quiet import apply_hub_quiet_env


def test_apply_hub_quiet_env_enables_progress_disables_hub_logs() -> None:
    env = apply_hub_quiet_env({"HF_HUB_DISABLE_PROGRESS_BARS": "1", "FOO": "bar"})
    assert env["FOO"] == "bar"
    assert "HF_HUB_DISABLE_PROGRESS_BARS" not in env
    assert env["HF_HUB_VERBOSITY"] == "error"
    assert env["TRANSFORMERS_VERBOSITY"] == "error"
