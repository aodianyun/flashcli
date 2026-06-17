"""Tests for vLLM report rows with HTTP stream metrics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

REPORT_PY = SCRIPTS_DIR / "bench_qwen36_report.py"


def test_report_vllm_http_stream_decode(tmp_path) -> None:
    workdir = tmp_path / "vllm"
    workdir.mkdir()
    (workdir / "manifest.json").write_text(
        json.dumps({"rounds": 2, "skip_first": 1}), encoding="utf-8"
    )
    rows = [
        {"round": 1, "wall_ms": 6000, "usage": {"completion_tokens": 64}, "bench": {}},
        {
            "round": 2,
            "wall_ms": 5940,
            "usage": {
                "prompt_tokens": 23,
                "completion_tokens": 64,
                "decode_tok_per_s": 11.3,
                "decode_ms": 5650.0,
                "ttft_ms": 290.0,
                "metrics_source": "vllm_http_stream",
            },
            "bench": {
                "client_ttft_ms": 290.0,
                "server_ttft_ms": 290.0,
                "metrics_source": "vllm_http_stream",
            },
        },
    ]
    with (workdir / "qwen36_short.metrics.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    out_dir = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(REPORT_PY), "--out", str(out_dir), "--vllm", str(workdir)],
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))["backends"][
        "vLLM"
    ]["cases"]["qwen36_short"]["metrics"]
    assert metrics["decode_tok_per_s_best"] == 11.3
    assert metrics["metrics_from_vllm_http"] is True
    assert metrics["prompt_tokens"] == 23
