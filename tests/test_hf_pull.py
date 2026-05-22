"""Tests for HuggingFace download mirror fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.models.pull import HF_MIRROR_ENDPOINT, _download_huggingface


def test_hf_mirror_retry_when_no_endpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    spec = {"repo": "org/model", "revision": "main"}
    calls: list[str] = []

    def fake_snapshot(**kwargs):
        calls.append(str(kwargs.get("endpoint", "")))
        if kwargs.get("endpoint") != HF_MIRROR_ENDPOINT:
            raise ConnectionError("hub unreachable")

    with patch("huggingface_hub.snapshot_download", fake_snapshot):
        _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == ["", HF_MIRROR_ENDPOINT]


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
