"""Tests for GitHub release download mirror / fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flashcli.runtime.mirror import (
    DEFAULT_GIT_PROXY_PREFIX,
    download_github_release_asset,
    github_release_download_urls,
    proxied_github_url,
)


_RELEASE_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "20241206/cpython-3.12.8%2B20241206-x86_64-unknown-linux-gnu-install_only.tar.gz"
)


def test_proxied_github_url() -> None:
    proxied = proxied_github_url(_RELEASE_URL, DEFAULT_GIT_PROXY_PREFIX)
    assert proxied.startswith(DEFAULT_GIT_PROXY_PREFIX.rstrip("/"))
    assert proxied.endswith(_RELEASE_URL)


def test_github_urls_mirror_first(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLASHCLI_USE_MIRROR", "1")
    monkeypatch.delenv("FLASHCLI_NO_MIRROR", raising=False)
    import flashcli_bundle.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False

    urls = github_release_download_urls(_RELEASE_URL)
    assert len(urls) >= 2
    assert urls[0][0].startswith(DEFAULT_GIT_PROXY_PREFIX.rstrip("/"))
    assert urls[0][1] == "GitHub mirror"
    assert urls[-1][0] == _RELEASE_URL


def test_github_urls_direct_first_without_mirror(monkeypatch) -> None:
    monkeypatch.delenv("FLASHCLI_USE_MIRROR", raising=False)
    monkeypatch.setenv("FLASHCLI_NO_MIRROR", "1")
    import flashcli_bundle.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False

    urls = github_release_download_urls(_RELEASE_URL)
    assert urls[0][0] == _RELEASE_URL
    assert urls[0][1] == "GitHub"
    assert any(label == "GitHub mirror" for _, label in urls[1:])


def test_github_urls_respect_disable_proxy(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_GIT_PROXY", "0")
    import flashcli_bundle.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False

    urls = github_release_download_urls(_RELEASE_URL)
    assert urls == [(_RELEASE_URL, "GitHub")]


def test_download_github_release_asset_fallback(monkeypatch, tmp_path: Path) -> None:
    import flashcli_bundle.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False
    monkeypatch.delenv("FLASHCLI_USE_MIRROR", raising=False)
    monkeypatch.setenv("FLASHCLI_NO_MIRROR", "1")

    calls: list[str] = []

    def fake_download(url: str, dest: Path, **kwargs: object) -> int:
        calls.append(url)
        if url == _RELEASE_URL:
            raise RuntimeError("blocked")
        dest.write_bytes(b"ok")
        return 2

    monkeypatch.setattr(
        "flashcli.util.download_progress.download_url_to_path",
        fake_download,
    )
    dest = tmp_path / "asset.tar.gz"
    nbytes = download_github_release_asset(_RELEASE_URL, dest, quiet=True)
    assert nbytes == 2
    assert dest.read_bytes() == b"ok"
    assert calls[0] == _RELEASE_URL
    assert calls[-1].startswith(DEFAULT_GIT_PROXY_PREFIX.rstrip("/"))


def test_download_github_release_asset_custom_proxy(monkeypatch, tmp_path: Path) -> None:
    import flashcli_bundle.runtime.mirror as mirror_mod

    mirror_mod._APPLIED = False
    monkeypatch.setenv("FLASHCLI_USE_MIRROR", "1")
    monkeypatch.setenv("FLASHCLI_GIT_PROXY", "https://example.proxy/")

    with patch(
        "flashcli.util.download_progress.download_url_to_path",
        return_value=3,
    ) as download_mock:
        dest = tmp_path / "asset.tar.gz"
        download_github_release_asset(_RELEASE_URL, dest, quiet=True)
        first_url = download_mock.call_args[0][0]
        assert first_url.startswith("https://example.proxy/")
