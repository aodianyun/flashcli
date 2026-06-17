"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

_MIRROR_ENV_KEYS = (
    "HF_ENDPOINT",
    "FLASHCLI_USE_MIRROR",
    "FLASHCLI_NO_MIRROR",
    "FLASHCLI_PREFER_HF_MIRROR",
    "FLASHCLI_PREFER_GITHUB_MIRROR",
    "FLASHCLI_GIT_PROXY",
    "PIP_INDEX_URL",
    "PIP_TRUSTED_HOST",
)


@pytest.fixture(autouse=True)
def _neutral_mirror_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests assume default (non-mirror) behavior unless they set env explicitly."""
    import flashcli.runtime.mirror as mirror_mod

    for key in _MIRROR_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mirror_mod, "_load_mirror_env_file", lambda: None)
    mirror_mod._APPLIED = False
