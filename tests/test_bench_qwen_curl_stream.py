"""Tests for bench_qwen_curl_stream.py vLLM metrics."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STREAM_PY = ROOT / "scripts" / "bench_qwen_curl_stream.py"


def _load_stream_mod():
    spec = importlib.util.spec_from_file_location("bench_qwen_curl_stream", STREAM_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vllm_http_stream_metrics_from_wall_and_client_ttft() -> None:
    mod = _load_stream_mod()
    usage: dict = {"completion_tokens": 64, "prompt_tokens": 23}
    bench: dict = {"wall_ms": 5940.0, "client_ttft_ms": 290.0}
    mod._apply_vllm_http_stream_metrics(usage, bench, bench_arm="vllm")
    assert usage["metrics_source"] == "vllm_http_stream"
    assert abs(usage["decode_tok_per_s"] - (64 * 1000.0 / (5940.0 - 290.0))) < 0.01
    assert bench["metrics_source"] == "vllm_http_stream"
    assert bench["server_ttft_ms"] == 290.0


def test_vllm_metrics_skipped_for_flashrt_arm() -> None:
    mod = _load_stream_mod()
    usage: dict = {"completion_tokens": 64}
    bench: dict = {"wall_ms": 1000.0, "client_ttft_ms": 200.0}
    mod._apply_vllm_http_stream_metrics(usage, bench, bench_arm="flashrt")
    assert "decode_tok_per_s" not in usage
    assert "metrics_source" not in usage
