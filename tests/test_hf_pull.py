"""Tests for HuggingFace download via Hub CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flashcli.models.hf_hub import HF_MIRROR_ENDPOINT, HF_OFFICIAL_ENDPOINT
from flashcli.models.pull import _download_huggingface


def test_hf_official_first_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("FLASHCLI_PREFER_HF_MIRROR", raising=False)
    spec = {"repo": "org/model"}
    calls: list[str] = []

    def fake_cli(*_args, **kwargs):
        calls.append(kwargs.get("endpoint", "MISSING"))
        if kwargs.get("endpoint") in ("", HF_OFFICIAL_ENDPOINT):
            return
        raise RuntimeError("mirror unreachable")

    with patch("flashcli.models.pull.filter_download_endpoints", lambda eps, **_: eps):
        with patch("flashcli.models.pull.run_hf_cli_download", fake_cli):
            _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == [""]


def test_hf_mirror_when_hf_endpoint_set(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_ENDPOINT", HF_MIRROR_ENDPOINT)
    spec = {"repo": "org/model"}
    calls: list[str] = []

    def fake_cli(*_args, **kwargs):
        calls.append(kwargs.get("endpoint", ""))

    with patch("flashcli.models.pull.run_hf_cli_download", fake_cli):
        _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == [HF_MIRROR_ENDPOINT]


def test_hf_official_falls_back_to_mirror(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    spec = {"repo": "org/model"}
    calls: list[str] = []

    def fake_cli(*_args, **kwargs):
        calls.append(kwargs.get("endpoint", "MISSING"))
        if kwargs.get("endpoint") in ("", HF_OFFICIAL_ENDPOINT):
            raise RuntimeError("official hub unreachable")
        return

    with patch("flashcli.models.pull.filter_download_endpoints", lambda eps, **_: eps):
        with patch("flashcli.models.pull.run_hf_cli_download", fake_cli):
            _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == ["", HF_MIRROR_ENDPOINT]


def test_hf_preserves_incomplete_cache_for_resume(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_ENDPOINT", HF_MIRROR_ENDPOINT)
    dest = tmp_path / "ckpt"
    dest.mkdir()
    (dest / ".cache").mkdir()
    spec = {"repo": "org/model"}

    with patch("flashcli.models.pull.run_hf_cli_download") as mock_dl:
        _download_huggingface(spec, dest, quiet=True)

    mock_dl.assert_called_once()
    assert (dest / ".cache").exists()


def test_hf_retries_same_endpoint(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_ENDPOINT", HF_MIRROR_ENDPOINT)
    monkeypatch.setenv("FLASHCLI_HF_DOWNLOAD_RETRIES", "3")
    monkeypatch.setenv("FLASHCLI_HF_RETRY_DELAY", "0")
    spec = {"repo": "org/model"}
    calls = 0

    def fake_cli(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("SSL handshake timed out")

    with patch("flashcli.models.pull.run_hf_cli_download", fake_cli):
        with patch(
            "flashcli.bundle.checkpoint.has_cached_weight_files",
            side_effect=[False, False, False, True],
        ):
            _download_huggingface(spec, tmp_path / "ckpt", quiet=True)

    assert calls == 3
