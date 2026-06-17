"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

_MIRROR_ENV_KEYS = (
    "HF_ENDPOINT",
    "FLASHCLI_USE_MIRROR",
    "FLASHCLI_PREFER_HF_MIRROR",
    "FLASHCLI_PREFER_GITHUB_MIRROR",
    "FLASHCLI_GIT_PROXY",
    "PIP_INDEX_URL",
    "PIP_TRUSTED_HOST",
)


def _reset_mirror_state() -> None:
    import flashcli.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False


def pytest_configure(config: pytest.Config) -> None:
    """Neutralize install-time mirror exports before test modules import flashcli."""
    os.environ["FLASHCLI_NO_MIRROR"] = "1"
    for key in _MIRROR_ENV_KEYS:
        os.environ.pop(key, None)
    _reset_mirror_state()


@pytest.fixture(autouse=True)
def _neutral_mirror_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests assume default (non-mirror) behavior unless they set env explicitly."""
    import flashcli.runtime.mirror as mirror_mod

    for key in _MIRROR_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("FLASHCLI_NO_MIRROR", raising=False)
    monkeypatch.setattr(mirror_mod, "_load_mirror_env_file", lambda: None)
    mirror_mod._APPLIED = False
