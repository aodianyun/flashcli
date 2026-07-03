"""GROOT N1.7 offline Cosmos backbone path resolution."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HUB_ENV = ROOT / "bundles" / "groot_n17" / "_groot_hub_env.py"


def _load_hub_env():
    spec = importlib.util.spec_from_file_location("groot_hub_env_test", _HUB_ENV)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_resolve_vlm_model_path_uses_extra_weight_env(tmp_path, monkeypatch) -> None:
    mod = _load_hub_env()
    backbone = tmp_path / "backbone"
    backbone.mkdir()
    (backbone / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FLASHCLI_EXTRA_WEIGHT_COSMOS_BACKBONE", str(backbone))
    resolved = mod.resolve_vlm_model_path("nvidia/Cosmos-Reason2-2B")
    assert resolved == str(backbone.resolve())


def test_resolve_vlm_model_path_keeps_hub_id_without_env(monkeypatch) -> None:
    mod = _load_hub_env()
    monkeypatch.delenv("FLASHCLI_EXTRA_WEIGHT_COSMOS_BACKBONE", raising=False)
    assert mod.resolve_vlm_model_path("nvidia/Cosmos-Reason2-2B") == "nvidia/Cosmos-Reason2-2B"


def test_prepare_gr00t_n17_hub_env_sets_offline_flags(monkeypatch) -> None:
    mod = _load_hub_env()
    for key in (
        "GROOT_HF_LOCAL_FIRST",
        "GROOT_SKIP_HF_MODEL_WEIGHTS",
        "GROOT_PATCH_MISTRAL",
        "GROOT_HF_QUIET",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "NO_ALBUMENTATIONS_UPDATE",
    ):
        monkeypatch.delenv(key, raising=False)
    mod.prepare_gr00t_n17_hub_env()
    assert os.environ["GROOT_HF_LOCAL_FIRST"] == "1"
    assert os.environ["GROOT_SKIP_HF_MODEL_WEIGHTS"] == "1"
    assert os.environ["GROOT_PATCH_MISTRAL"] == "1"
    assert os.environ["GROOT_HF_QUIET"] == "1"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
