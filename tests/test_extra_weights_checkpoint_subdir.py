"""Tests for extra_weights with checkpoint_subdir (e.g. GROOT Qwen3 tokenizer)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flashcli.bundle.weights import download_extra_weights, ensure_checkpoint
from flashcli_bundle.manifest import load_bundle_manifest
from flashcli_bundle.preset import Preset
from flashcli_bundle.checkpoint import extra_weights_ready
from flashcli_bundle.weights import extra_weight_dest, require_extra_weights_cached


def test_groot_manifest_declares_qwen3_extra_weights() -> None:
    root = Path(__file__).resolve().parents[1] / "bundles" / "groot_n16"
    manifest = load_bundle_manifest(root)
    extra = manifest.raw.get("extra_weights") or {}
    spec = extra.get("qwen3_tokenizer")
    assert isinstance(spec, dict)
    assert spec.get("repo") == "Qwen/Qwen3-1.7B"
    assert spec.get("checkpoint_subdir") == "tokenizer"
    assert spec.get("require_any_patterns")


def test_extra_weight_dest_checkpoint_subdir(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    spec = {
        "repo": "Qwen/Qwen3-1.7B",
        "checkpoint_subdir": "tokenizer",
    }
    dest = extra_weight_dest(None, "qwen3_tokenizer", spec, checkpoint_dir=checkpoint)
    assert dest == checkpoint / "tokenizer"


def test_extra_weights_ready_require_any_one_tokenizer_file(tmp_path: Path) -> None:
    tok = tmp_path / "tokenizer"
    tok.mkdir()
    (tok / "tokenizer.json").write_text("{}", encoding="utf-8")
    spec = {
        "repo": "Qwen/Qwen3-1.7B",
        "allow_patterns": ["tokenizer*", "vocab*", "merges*"],
        "require_any_patterns": ["tokenizer.json", "tokenizer_config.json"],
        "checkpoint_subdir": "tokenizer",
    }
    assert extra_weights_ready(tok, spec)


def test_extra_weights_ready_require_any_incomplete(tmp_path: Path) -> None:
    tok = tmp_path / "tokenizer"
    tok.mkdir()
    (tok / ".cache").mkdir()
    spec = {
        "allow_patterns": ["tokenizer*", "vocab*", "merges*"],
        "require_any_patterns": ["tokenizer.json", "tokenizer_config.json"],
    }
    assert not extra_weights_ready(tok, spec)


def test_download_extra_weights_checkpoint_subdir(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "bundles" / "groot_n16"
    manifest = load_bundle_manifest(root)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    calls: list[Path] = []

    def _fake_download(spec, dest, *, quiet=False):
        del spec, quiet
        calls.append(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "tokenizer.json").write_text("{}", encoding="utf-8")

    with patch("flashcli.bundle.weights.download_weights", side_effect=_fake_download):
        download_extra_weights(
            manifest,
            checkpoint_dir=checkpoint,
            quiet=True,
        )

    assert calls == [checkpoint / "tokenizer"]
    require_extra_weights_cached(
        manifest, checkpoint_dir=checkpoint
    )


def test_ensure_checkpoint_downloads_extra_into_checkpoint_subdir(
    monkeypatch, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[1] / "bundles" / "groot_n16"
    manifest = load_bundle_manifest(root)
    preset = Preset(
        name="bundles/groot_n16",
        raw={"engine": "model_bundle"},
        cache_key="groot_n16/test",
    )
    home = tmp_path / "home"
    monkeypatch.setenv("FLASHCLI_HOME", str(home))
    from flashcli_bundle import paths as config

    config.FLASHCLI_HOME = home
    config.MODELS_DIR = home / "models"

    main_calls: list[Path] = []
    extra_calls: list[Path] = []

    def _fake_main(spec, dest, *, quiet=False):
        del spec, quiet
        main_calls.append(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "model.safetensors").write_bytes(b"x")

    def _fake_extra(bundle, *, variant=None, checkpoint_dir=None, quiet=False, download=True):
        del bundle, variant, quiet, download
        assert checkpoint_dir is not None
        dest = checkpoint_dir / "tokenizer"
        extra_calls.append(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "tokenizer.json").write_text("{}", encoding="utf-8")
        (dest / "tokenizer_config.json").write_text("{}", encoding="utf-8")

    with (
        patch("flashcli.bundle.weights.download_merged_weights", side_effect=_fake_main),
        patch("flashcli.bundle.weights.download_extra_weights", side_effect=_fake_extra),
    ):
        ckpt = ensure_checkpoint(preset, manifest, quiet=True, download=True)

    assert ckpt == config.MODELS_DIR / "groot_n16/test" / "checkpoint"
    assert main_calls == [ckpt]
    assert extra_calls == [ckpt / "tokenizer"]
