"""Tests for mirror_enabled precedence (NO_MIRROR vs USE_MIRROR)."""

from __future__ import annotations

from flashcli.runtime.mirror import mirror_enabled


def test_no_mirror_overrides_use_mirror(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_USE_MIRROR", "1")
    monkeypatch.setenv("FLASHCLI_NO_MIRROR", "1")
    assert mirror_enabled() is False
