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


def test_pytorch_ckpt_is_usable(tmp_path: Path) -> None:
    dest = tmp_path / "melband"
    dest.mkdir()
    (dest / "MelBandRoformer.ckpt").write_bytes(b"fake")
    (dest / "config_vocals_mel_band_roformer.yaml").write_text("x: 1\n")

    assert has_usable_checkpoint(dest)
    assert has_cached_weight_files(dest, None)


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


def test_pi05_incomplete_sidecars_resume_download(monkeypatch, tmp_path: Path) -> None:
    """Incomplete pi05 cache must not skip ``hf download``."""
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    dest = tmp_path / "checkpoint"
    dest.mkdir()
    (dest / "config.json").write_text("{}", encoding="utf-8")
    (dest / "policy_preprocessor_step_2_normalizer_processor.safetensors").write_bytes(
        b"x"
    )
    (dest / "policy_postprocessor_step_0_unnormalizer_processor.safetensors").write_bytes(
        b"x"
    )
    spec = {
        "repo": "lerobot/pi05_libero_finetuned_v044",
        "require_norm_stats": True,
    }

    with patch("flashcli.models.pull.run_hf_cli_download") as mock_dl:
        def _write_weights(*_args, **_kwargs) -> None:
            (dest / "model.safetensors").write_bytes(b"x")

        mock_dl.side_effect = _write_weights
        _download_huggingface(spec, dest, quiet=True)

    mock_dl.assert_called_once()


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


def test_hf_extra_weights_downloads_each_pattern_until_require_any(
    tmp_path: Path, monkeypatch
) -> None:
    """Hub fetches one file per CLI call; flashcli requests each pattern in order."""
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    dest = tmp_path / "tokenizer"
    dest.mkdir()
    spec = {
        "repo": "Qwen/Qwen3-1.7B",
        "allow_patterns": [
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
        ],
        "require_any_patterns": ["tokenizer.json", "tokenizer_config.json"],
        "checkpoint_subdir": "tokenizer",
    }
    seen: list[list[str] | None] = []

    def _per_pattern_download(
        *_args,
        allow_patterns: list[str] | None = None,
        **_kwargs,
    ) -> None:
        seen.append(allow_patterns)
        if allow_patterns == ["tokenizer.json"]:
            (dest / "tokenizer.json").write_text("{}", encoding="utf-8")

    with patch(
        "flashcli.models.pull.run_hf_cli_download",
        side_effect=_per_pattern_download,
    ):
        _download_huggingface(spec, dest, quiet=True)

    assert seen[0] == ["tokenizer.json"]
    assert (dest / "tokenizer.json").is_file()
