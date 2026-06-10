"""Tests for FlashHub-first python-standalone resolution."""

from __future__ import annotations

from flashcli.bundle.python_standalone_hub import (
    DEFAULT_PYTHON_REPO,
    enrich_manifest_from_index,
    python_repo_url,
    resolve_standalone_asset,
    standalone_download_urls,
)
from flashcli.standalone_release import StandaloneAsset


class _FakeEntry:
    def __init__(self, path: str, url: str, md5: str | None = None, size: int | None = None):
        self.path = path
        self.url = url
        self.md5 = md5
        self.size = size


class _FakeIndex:
    def __init__(self, files):
        self.files = files


def test_python_repo_url_default() -> None:
    assert python_repo_url() == DEFAULT_PYTHON_REPO


def test_python_repo_url_disabled(monkeypatch) -> None:
    monkeypatch.setenv("FLASHCLI_PYTHON_REPO", "0")
    assert python_repo_url() is None


def test_enrich_manifest_rewrites_cdn_urls() -> None:
    manifest = {
        "standalone_tag": "20260602",
        "files": [
            {
                "py_minor": "312",
                "triplet": "x86_64-unknown-linux-gnu",
                "filename": "cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20260602/cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "md5": "old",
            }
        ],
    }
    index = _FakeIndex(
        [
            _FakeEntry(
                "20260602/x86_64-unknown-linux-gnu/cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "https://flashhub-cdn.aodianyun.com/repo/7/versions/9/20260602/x86_64-unknown-linux-gnu/cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                md5="b18856753dc5c2ec7f1446fc3e327f24",
                size=111092240,
            )
        ]
    )
    enriched = enrich_manifest_from_index(manifest, index)
    row = enriched["files"][0]
    assert row["url"].startswith("https://flashhub-cdn.aodianyun.com/")
    assert row["md5"] == "b18856753dc5c2ec7f1446fc3e327f24"
    assert row["size"] == 111092240


def test_standalone_download_urls_flashhub_first() -> None:
    asset = StandaloneAsset(
        py_minor="312",
        triplet="x86_64-unknown-linux-gnu",
        tag="20260602",
        filename="cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
        url="https://flashhub-cdn.aodianyun.com/repo/7/versions/9/20260602/x86_64-unknown-linux-gnu/cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
    )
    urls = standalone_download_urls(asset, repo_url=None)
    assert urls[0][1] == "FlashHub"
    assert "github.com" in urls[-1][0]


def test_resolve_prefers_flashhub(monkeypatch) -> None:
    asset = StandaloneAsset(
        py_minor="312",
        triplet="x86_64-unknown-linux-gnu",
        tag="20260602",
        filename="cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
        url="https://flashhub-cdn.example/cpython-3.12.13.tar.gz",
    )

    def fake_fetch(_repo, **kwargs):
        return {
            "standalone_tag": "20260602",
            "files": [
                {
                    "py_minor": "312",
                    "triplet": "x86_64-unknown-linux-gnu",
                    "tag": "20260602",
                    "filename": "cpython-3.12.13+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                    "url": "https://flashhub-cdn.example/cpython-3.12.13.tar.gz",
                }
            ],
        }

    monkeypatch.setattr(
        "flashcli.bundle.python_standalone_hub.fetch_flashhub_manifest",
        fake_fetch,
    )
    monkeypatch.setattr(
        "flashcli.bundle.python_standalone_hub._local_manifest_path",
        lambda: None,
    )
    monkeypatch.setattr(
        "flashcli.bundle.python_standalone_hub.find_standalone_asset",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not hit github")),
    )

    got = resolve_standalone_asset("312", "x86_64-unknown-linux-gnu", quiet=True)
    assert got.url.startswith("https://flashhub-cdn.example/")
