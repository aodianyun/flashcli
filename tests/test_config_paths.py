"""Tests for FlashHub API config."""

from __future__ import annotations

from flashcli import config


def test_flashhub_api_base_default() -> None:
    assert config.FLASHHUB_API_BASE.startswith("https://")
    assert config.FLASHHUB_API_BASE.endswith("/api/v1/repos")
