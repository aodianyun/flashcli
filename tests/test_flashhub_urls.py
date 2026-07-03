"""FlashHub API URL construction (unified domain + env overrides)."""

from __future__ import annotations

from flashcli.bundle.python_standalone_hub import python_repo_url
from flashcli_bundle.paths import (
    default_python_standalone_repo_url,
    flashhub_repo_url,
    python_standalone_repo_url,
)


def test_flashhub_repo_url_uses_colon_version() -> None:
    url = flashhub_repo_url("flashcli-bundle", "pi05_libero", "1.0.4")
    assert url.endswith("/flashcli-bundle/pi05_libero:1.0.4")
    assert "flashhub-api.aodianyun.com" in url


def test_default_python_standalone_follows_flashhub_api_base(monkeypatch) -> None:
    monkeypatch.delenv("FLASHCLI_PYTHON_REPO", raising=False)
    monkeypatch.delenv("FLASHCLI_PYTHON_STANDALONE_VERSION", raising=False)
    monkeypatch.setenv(
        "FLASHCLI_FLASHHUB_API",
        "https://flashhub-api.example.com/api/v1/repos",
    )
    url = default_python_standalone_repo_url()
    assert (
        url == "https://flashhub-api.example.com/api/v1/repos/"
        "flashcli-bundle/python-standalone:1.0.0"
    )
    assert python_repo_url() == url


def test_python_standalone_repo_override(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_PYTHON_REPO", "https://custom.example/repo:9")
    assert python_standalone_repo_url() == "https://custom.example/repo:9"


def test_python_standalone_repo_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_PYTHON_REPO", "0")
    assert python_standalone_repo_url() is None
    assert python_repo_url() is None


def test_python_standalone_version_env(monkeypatch) -> None:
    monkeypatch.delenv("FLASHCLI_PYTHON_REPO", raising=False)
    monkeypatch.setenv("FLASHCLI_PYTHON_STANDALONE_VERSION", "2.0.0")
    url = default_python_standalone_repo_url()
    assert url.endswith("flashcli-bundle/python-standalone:2.0.0")
