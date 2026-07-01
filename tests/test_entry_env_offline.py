"""Bundle entry env: offline hub + extra_weights validation at run time."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flashcli.models.registry import Preset
from flashcli_bundle.entry_env import apply_offline_hub_env, inject_entry_env
from flashcli_bundle.manifest import load_bundle_manifest_data


def test_apply_offline_hub_env_sets_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        monkeypatch.delenv(key, raising=False)
    apply_offline_hub_env()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_DATASETS_OFFLINE"] == "1"


def test_inject_entry_env_rejects_incomplete_extra_weights(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    manifest = load_bundle_manifest_data(
        {
            "format": "flashcli-model-bundle",
            "format_version": 3,
            "protocol_version": 1,
            "name": "groot_n16",
            "python_abi": "312",
            "entry": {"run": {"module": "run", "attr": "main", "mode": "script"}},
            "extra_weights": {
                "qwen3_tokenizer": {
                    "source": "huggingface",
                    "repo": "Qwen/Qwen3-1.7B",
                    "allow_patterns": [
                        "tokenizer.json",
                        "tokenizer_config.json",
                        "vocab.json",
                        "merges.txt",
                    ],
                    "checkpoint_subdir": "tokenizer",
                }
            },
        },
        bundle_root=bundle_root,
    )
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    tok = checkpoint / "tokenizer"
    tok.mkdir()
    (tok / "tokenizer.json").write_text("{}", encoding="utf-8")

    preset = Preset(name="bundles/groot_n16", raw={}, cache_key="groot_n16/test")

    with pytest.raises(FileNotFoundError, match="Extra weights 'qwen3_tokenizer'"):
        inject_entry_env(
            mode="script",
            preset=preset,
            bundle=manifest,
            checkpoint=checkpoint,
            variant=None,
        )
