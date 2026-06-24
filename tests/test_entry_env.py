"""Tests for engine vs script bundle entry environment injection."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flashcli_bundle.entry_env import (
    ENV_CHECKPOINT,
    ENV_MTP_CHECKPOINT,
    ENV_PRESET,
    ENV_VARIANT,
    extra_weight_env_name,
    inject_engine_entry_env,
    inject_script_entry_env,
)
from flashcli_bundle.manifest import load_bundle_manifest_data
from flashcli_bundle.preset import Preset


def _bundle_manifest(tmp_path: Path, *, mode: str = "script"):
    data = {
        "format": "flashcli-model-bundle",
        "format_version": 3,
        "protocol_version": 1,
        "name": "demo",
        "python_abi": "312",
        "entry": {"run": {"module": "run", "attr": "main", "mode": mode}},
        "run_options": [
            {
                "name": "prompt",
                "type": "string",
                "default": "x",
                "help": "p",
                "phase": "predict",
            }
        ],
        "extra_weights": {
            "vocoder": {
                "source": "huggingface",
                "repo": "org/vocoder",
                "cache_name": "demo/1.0.0/vocoder",
            }
        },
        "env": {
            "MY_ENGINE_ONLY": "{bundle_root}/data",
            "FLASHRT_QWEN36_MTP_CKPT_DIR": "{models_dir}/demo/1.0.0/vocoder",
        },
        "runtime": {"x-py312": "runtime/x-py312"},
    }
    return load_bundle_manifest_data(data, bundle_root=tmp_path)


def test_extra_weight_env_name() -> None:
    assert extra_weight_env_name("mtp_fp8") == "FLASHCLI_EXTRA_WEIGHT_MTP_FP8"
    assert extra_weight_env_name("vocoder") == "FLASHCLI_EXTRA_WEIGHT_VOCODER"


def test_inject_script_entry_env_sets_platform_vars(
    tmp_path: Path, monkeypatch
) -> None:
    from flashcli_bundle import paths as flashcli_paths

    monkeypatch.setattr(flashcli_paths, "MODELS_DIR", tmp_path / "models")
    manifest = _bundle_manifest(tmp_path)
    ckpt = tmp_path / "checkpoint"
    ckpt.mkdir()
    preset = Preset(name="demo/demo:1.0.0@v1", raw={"engine": "model_bundle"})

    inject_script_entry_env(
        preset=preset,
        bundle=manifest,
        checkpoint=ckpt,
        variant="v1",
    )

    assert os.environ[ENV_CHECKPOINT] == str(ckpt.resolve())
    assert os.environ[ENV_PRESET] == preset.name
    assert os.environ[ENV_VARIANT] == "v1"
    assert os.environ["FLASHCLI_BUNDLE_ROOT"] == str(tmp_path.resolve())
    assert os.environ["FLASHCLI_EXTRA_WEIGHT_VOCODER"] == str(
        (tmp_path / "models" / "demo/1.0.0/vocoder").resolve()
    )
    assert "MY_ENGINE_ONLY" not in os.environ
    assert ENV_MTP_CHECKPOINT not in os.environ


def test_inject_engine_entry_env_applies_manifest_env(tmp_path: Path, monkeypatch) -> None:
    from flashcli_bundle import paths as flashcli_paths

    monkeypatch.setattr(flashcli_paths, "MODELS_DIR", tmp_path / "models")
    manifest = _bundle_manifest(tmp_path, mode="engine")

    inject_engine_entry_env(manifest, variant=None)

    assert os.environ["MY_ENGINE_ONLY"] == str((tmp_path / "data").resolve())
    assert ENV_CHECKPOINT not in os.environ


def test_inject_engine_mtp_override(tmp_path: Path) -> None:
    manifest = _bundle_manifest(tmp_path, mode="engine")
    mtp = tmp_path / "mtp"
    mtp.mkdir()

    inject_engine_entry_env(manifest, variant=None, mtp_checkpoint=mtp)

    assert os.environ[ENV_MTP_CHECKPOINT] == str(mtp.resolve())


def test_inject_engine_mtp_override_missing_raises(tmp_path: Path) -> None:
    manifest = _bundle_manifest(tmp_path, mode="engine")
    with pytest.raises(FileNotFoundError, match="MTP checkpoint not found"):
        inject_engine_entry_env(
            manifest,
            variant=None,
            mtp_checkpoint=tmp_path / "missing",
        )
