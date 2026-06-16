"""Tests for extra-weight cache detection (e.g. qwen36 MTP)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flashcli.bundle.checkpoint import has_cached_weight_files, has_usable_checkpoint
from flashcli.models.pull import _download_huggingface


def test_mtp_safetensors_only_is_usable(tmp_path: Path) -> None:
    dest = tmp_path / "mtp_fp8"
    dest.mkdir()
    (dest / "mtp.safetensors").write_bytes(b"fake")

    assert has_usable_checkpoint(dest)
    assert has_cached_weight_files(dest, ["mtp.safetensors"])


def test_mtp_download_skipped_when_cached(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    dest = tmp_path / "mtp_fp8"
    dest.mkdir()
    (dest / "mtp.safetensors").write_bytes(b"fake")
    spec = {
        "repo": "Qwen/Qwen3.6-27B-FP8",
        "allow_patterns": ["mtp.safetensors"],
    }

    with patch("flashcli.models.pull.run_hf_cli_download") as mock_dl:
        _download_huggingface(spec, dest, quiet=True)

    mock_dl.assert_not_called()


def test_mtp_incomplete_cache_is_resumed_before_download(
    monkeypatch, tmp_path: Path
) -> None:
    """Incomplete cache (.cache only) is kept so ``hf download`` can resume."""
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    dest = tmp_path / "mtp_fp8"
    dest.mkdir()
    (dest / ".cache").mkdir()
    spec = {
        "repo": "Qwen/Qwen3.6-27B-FP8",
        "allow_patterns": ["mtp.safetensors"],
    }

    with patch("flashcli.models.pull.run_hf_cli_download") as mock_dl:
        def _write_weights(*_args, **_kwargs) -> None:
            (dest / "mtp.safetensors").write_bytes(b"fake")

        mock_dl.side_effect = _write_weights
        _download_huggingface(spec, dest, quiet=True)

    assert dest.is_dir()
    assert (dest / ".cache").exists()
    mock_dl.assert_called_once()
