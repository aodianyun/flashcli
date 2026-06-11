"""Tests for checkpoint completeness (weights + pi05 norm stats sidecars)."""

from __future__ import annotations

from pathlib import Path

from flashcli.bundle.checkpoint import (
    has_norm_stats_sources,
    has_usable_checkpoint,
    weights_require_norm_stats,
)


def test_weights_require_norm_stats_auto_for_pi05() -> None:
    assert weights_require_norm_stats({"repo": "lerobot/pi05_libero_finetuned_v044"})
    assert not weights_require_norm_stats({"repo": "Qwen/Qwen3-8B"})


def test_pi05_incomplete_without_processor_sidecars(tmp_path: Path) -> None:
    ckpt = tmp_path / "checkpoint"
    ckpt.mkdir()
    (ckpt / "model.safetensors").write_bytes(b"x")
    (ckpt / "config.json").write_text("{}", encoding="utf-8")

    assert not has_usable_checkpoint(
        ckpt,
        require_norm_stats=weights_require_norm_stats(
            {"repo": "lerobot/pi05_libero_finetuned_v044"}
        ),
    )


def test_pi05_complete_with_processor_sidecars(tmp_path: Path) -> None:
    ckpt = tmp_path / "checkpoint"
    ckpt.mkdir()
    (ckpt / "model.safetensors").write_bytes(b"x")
    (ckpt / "policy_preprocessor_step_2_normalizer_processor.safetensors").write_bytes(
        b"x"
    )
    (ckpt / "policy_postprocessor_step_0_unnormalizer_processor.safetensors").write_bytes(
        b"x"
    )

    assert has_norm_stats_sources(ckpt)
    assert has_usable_checkpoint(
        ckpt,
        require_norm_stats=weights_require_norm_stats(
            {"repo": "lerobot/pi05_libero_finetuned_v044"}
        ),
    )
