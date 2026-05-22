"""Tests for HuggingFace download mirror fallback."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.models.pull import HF_MIRROR_ENDPOINT, _download_huggingface, _hub_tqdm_classes


def test_hf_mirror_retry_when_no_endpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("FLASHCLI_PREFER_HF_MIRROR", raising=False)
    spec = {"repo": "org/model", "revision": "main"}
    calls: list[str] = []

    def fake_snapshot(**kwargs):
        calls.append(str(kwargs.get("endpoint", "")))
        if kwargs.get("endpoint") != HF_MIRROR_ENDPOINT:
            raise ConnectionError("hub unreachable")

    with patch("huggingface_hub.snapshot_download", fake_snapshot):
        _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == ["", HF_MIRROR_ENDPOINT]


def test_hf_mirror_first_when_preferred(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setenv("FLASHCLI_PREFER_HF_MIRROR", "1")
    spec = {"repo": "org/model"}
    calls: list[str] = []

    def fake_snapshot(**kwargs):
        calls.append(str(kwargs.get("endpoint", "")))
        if kwargs.get("endpoint"):
            return
        raise ConnectionError("official hub unreachable")

    with patch("huggingface_hub.snapshot_download", fake_snapshot):
        _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == [HF_MIRROR_ENDPOINT, ""]


def test_hf_cleans_incomplete_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    dest = tmp_path / "ckpt"
    dest.mkdir()
    (dest / ".cache").mkdir()
    spec = {"repo": "org/model"}

    with patch("huggingface_hub.snapshot_download") as mock_dl:
        _download_huggingface(spec, dest, quiet=True)

    mock_dl.assert_called_once()
    assert not (dest / ".cache").exists()


def test_hf_no_mirror_retry_when_endpoint_set(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_ENDPOINT", "https://custom.example")
    spec = {"repo": "org/model"}

    with patch(
        "huggingface_hub.snapshot_download",
        side_effect=ConnectionError("fail"),
    ) as mock_dl:
        with pytest.raises(RuntimeError, match="custom.example"):
            _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert mock_dl.call_count == 1


def test_hf_passes_tqdm_class_when_not_quiet(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    spec = {"repo": "org/model"}
    captured: dict = {}

    def fake_snapshot(**kwargs):
        captured.update(kwargs)

    with patch("huggingface_hub.snapshot_download", fake_snapshot):
        _download_huggingface(spec, tmp_path / "ckpt", quiet=False)

    assert captured.get("tqdm_class") is _hub_tqdm_classes()[0]
    assert os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") != "1"


def test_hf_network_hint_on_local_entry_not_found(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HF_ENDPOINT", "https://custom.example")
    spec = {"repo": "org/model"}

    class LocalEntryNotFoundError(Exception):
        pass

    with patch(
        "huggingface_hub.snapshot_download",
        side_effect=LocalEntryNotFoundError("no snapshot"),
    ):
        with pytest.raises(RuntimeError, match="Network note"):
            _download_huggingface(spec, tmp_path / "ckpt", quiet=True)
