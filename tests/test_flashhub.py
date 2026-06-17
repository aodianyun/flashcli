"""Tests for FlashHub repo index parsing."""

from __future__ import annotations

import json
from pathlib import Path

from flashcli_bundle.flashhub import (
    RepoIndex,
    _parse_index_payload,
    _path_from_download_url,
)
from flashcli.bundle.flashhub import download_manifest_from_repo


def test_path_from_download_url() -> None:
    url = (
        "https://flashhub-cdn.aodianyun.com/repo/5/versions/8/"
        "runtime/sm89-cu124-linux-x86_64-py312/flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so"
    )
    assert _path_from_download_url(url) == (
        "runtime/sm89-cu124-linux-x86_64-py312/"
        "flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so"
    )
    assert _path_from_download_url(
        "https://flashhub-cdn.aodianyun.com/repo/5/versions/8/flashcli-bundle.json"
    ) == "flashcli-bundle.json"


def test_parse_flashhub_api_payload() -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "files": [
                {
                    "download_url": "https://flashhub-cdn.aodianyun.com/repo/5/versions/8/flashcli-bundle.json",
                    "file_name": "flashcli-bundle.json",
                    "file_size": 984,
                    "md5_hash": "1894f85986ecdb6c5aba0cd3bcf5ab9e",
                },
                {
                    "download_url": (
                        "https://flashhub-cdn.aodianyun.com/repo/5/versions/8/"
                        "runtime/sm89-cu124-linux-x86_64-py312/"
                        "flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so"
                    ),
                    "file_name": "flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so",
                    "file_size": 5625864,
                    "md5_hash": "1c14aa3bfc518977d58c6d53bb876acc",
                },
            ]
        },
    }
    index = _parse_index_payload(
        payload,
        repo_url="https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero/1.0.2",
    )
    assert isinstance(index, RepoIndex)
    manifest = index.find("flashcli-bundle.json")
    assert manifest is not None
    assert manifest.url.endswith("/flashcli-bundle.json")
    assert manifest.md5 == "1894f85986ecdb6c5aba0cd3bcf5ab9e"
    so = index.find(
        "runtime/sm89-cu124-linux-x86_64-py312/flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so"
    )
    assert so is not None
    assert so.size == 5625864


def test_parse_flashhub_api_error() -> None:
    try:
        _parse_index_payload({"code": 1, "message": "not found", "data": {}}, repo_url="https://x")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "code=1" in str(exc)


def test_download_manifest_mock(tmp_path: Path, monkeypatch) -> None:
    from flashcli_bundle import flashhub

    manifest = {"format": "flashcli-model-bundle", "format_version": 3, "protocol_version": 1, "name": "t"}

    def fake_download(entry, dest, **kwargs):
        dest.write_text(json.dumps(manifest), encoding="utf-8")
        return dest

    monkeypatch.setattr(flashhub, "fetch_repo_index", lambda repo_url, **kwargs: flashhub.RepoIndex(
        repo_url=repo_url,
        files=[
            flashhub.RepoFile(
                path="flashcli-bundle.json",
                url="https://flashhub-cdn.example.com/repo/1/versions/2/flashcli-bundle.json",
                size=100,
            )
        ],
    ))
    monkeypatch.setattr(flashhub, "download_repo_file", fake_download)
    out = tmp_path / "m.json"
    data = flashhub.download_manifest_from_repo(
        "https://flashhub.example.com/api/v1/repos/org/model/1.0.0",
        out,
    )
    assert data["name"] == "t"
