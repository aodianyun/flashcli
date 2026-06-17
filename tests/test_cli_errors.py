"""Tests for concise CLI error formatting."""

from __future__ import annotations

import pytest

from flashcli.cli_errors import (
    FlashHubNotFoundError,
    flashhub_error_from_fetch,
    format_user_error,
    hints_for,
    is_user_facing_error,
)
from flashcli.bundle.preflight import BundleEnvironmentError


def test_flashhub_not_found_is_user_facing() -> None:
    exc = FlashHubNotFoundError("FlashHub repo not found: flashcli-bundle/qwen_nvfp4:1.0.10")
    assert is_user_facing_error(exc)
    text = format_user_error(exc)
    assert "error:" in text
    assert "hint:" in text
    assert "1.0.10" in text
    assert "flashcli models list" in text


def test_runtime_404_is_user_facing() -> None:
    exc = RuntimeError(
        "Failed to fetch https://flashhub-api.example/api/v1/repos/"
        "flashcli-bundle/qwen_nvfp4:1.0.10: HTTP Error 404: Not Found"
    )
    assert is_user_facing_error(exc)


def test_flashhub_error_from_fetch_404() -> None:
    url = "https://flashhub-api.example/api/v1/repos/flashcli-bundle/qwen_nvfp4:1.0.10"
    cause = RuntimeError(f"Failed to fetch {url}: HTTP Error 404: Not Found")
    err = flashhub_error_from_fetch(url, cause)
    assert isinstance(err, FlashHubNotFoundError)
    assert "qwen_nvfp4:1.0.10" in str(err)


def test_bundle_environment_hints() -> None:
    exc = BundleEnvironmentError("GPU mismatch")
    hints = hints_for(exc)
    assert any("flashcli models envs" in h for h in hints)


def test_internal_error_not_user_facing() -> None:
    assert not is_user_facing_error(KeyError("unexpected"))
