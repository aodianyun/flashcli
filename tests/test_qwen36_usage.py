"""Tests for qwen36 engine usage field mapping."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _qwen_util():
    path = (
        Path(__file__).resolve().parents[1] / "bundles/qwen_nvfp4/_qwen_util.py"
    )
    spec = importlib.util.spec_from_file_location("bundle_qwen_util_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_usage_from_qwen36_engine_prefers_decode_tok_per_s() -> None:
    mod = _qwen_util()
    usage = mod.usage_from_qwen36_engine(
        {
            "prompt_tokens": 19,
            "completion_tokens": 64,
            "decode_tok_per_s": 114.0,
            "e2e_tok_per_s": 53.3,
            "wall_s": 1.2,
            "prefill_ms": 100.0,
            "decode_ms": 560.0,
        }
    )
    assert usage["tok_per_s"] == 114.0
    assert usage["decode_tok_per_s"] == 114.0
    assert usage["e2e_tok_per_s"] == 53.3
    assert usage["prefill_ms"] == 100.0


def test_usage_from_qwen36_engine_falls_back_to_e2e() -> None:
    mod = _qwen_util()
    usage = mod.usage_from_qwen36_engine(
        {
            "prompt_tokens": 19,
            "completion_tokens": 64,
            "decode_tok_per_s": 0.0,
            "e2e_tok_per_s": 53.3,
            "wall_s": 1.2,
        }
    )
    assert usage["tok_per_s"] == 53.3
