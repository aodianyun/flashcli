"""Tests for bench_qwen36_report.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PY = ROOT / "scripts" / "bench_qwen36_report.py"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_report_summarize_and_compare(tmp_path: Path) -> None:
    flashcli_dir = tmp_path / "flashcli"
    flashrt_dir = tmp_path / "flashrt"
    flashcli_dir.mkdir()
    flashrt_dir.mkdir()

    manifest = {
        "rounds": 3,
        "skip_first": 1,
        "backend": "test",
    }
    for d in (flashcli_dir, flashrt_dir):
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    sample_rows = [
        {
            "round": 1,
            "wall_ms": 1000,
            "usage": {
                "prompt_tokens": 19,
                "completion_tokens": 64,
                "ttft_ms": 450.0,
                "tok_per_s": 80.0,
                "route": "short_spec",
            },
            "bench": {"client_ttft_ms": 460.0},
        },
        {
            "round": 2,
            "wall_ms": 900,
            "usage": {
                "prompt_tokens": 19,
                "completion_tokens": 64,
                "ttft_ms": 440.0,
                "tok_per_s": 85.0,
                "route": "short_spec",
            },
            "bench": {"client_ttft_ms": 445.0},
        },
        {
            "round": 3,
            "wall_ms": 950,
            "usage": {
                "prompt_tokens": 19,
                "completion_tokens": 64,
                "ttft_ms": 445.0,
                "tok_per_s": 82.5,
                "route": "short_spec",
            },
            "bench": {"client_ttft_ms": 450.0},
        },
    ]
    _write_jsonl(flashcli_dir / "qwen36_short.metrics.jsonl", sample_rows)
    slower = json.loads(json.dumps(sample_rows))
    for row in slower:
        row["usage"]["tok_per_s"] = float(row["usage"]["tok_per_s"]) - 5.0
    _write_jsonl(flashrt_dir / "qwen36_short.metrics.jsonl", slower)

    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPORT_PY),
            "--out",
            str(out_dir),
            "--flashcli",
            str(flashcli_dir),
            "--pytorch",
            str(flashrt_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (out_dir / "REPORT.md").is_file()
    assert (out_dir / "report.json").is_file()
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    fc = payload["backends"]["flashcli + FlashRT"]["cases"]["qwen36_short"]["metrics"]
    assert fc["decode_tok_per_s_best"] == 83.75
    assert "Comparison" in proc.stdout


def test_report_estimates_decode_when_usage_lacks_timing(tmp_path: Path) -> None:
    workdir = tmp_path / "flashcli"
    workdir.mkdir()
    (workdir / "manifest.json").write_text(
        json.dumps({"rounds": 2, "skip_first": 1}), encoding="utf-8"
    )
    _write_jsonl(
        workdir / "qwen36_short.metrics.jsonl",
        [
            {"round": 1, "wall_ms": 1000, "usage": {"prompt_tokens": 23, "completion_tokens": 64}, "bench": {}},
            {
                "round": 2,
                "wall_ms": 1338,
                "usage": {"prompt_tokens": 23, "completion_tokens": 64},
                "bench": {"client_ttft_ms": 400.0},
            },
        ],
    )
    out_dir = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(REPORT_PY), "--out", str(out_dir), "--flashcli", str(workdir)],
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))["backends"][
        "flashcli + FlashRT"
    ]["cases"]["qwen36_short"]["metrics"]
    assert metrics["server_ttft_ms"] == 400.0
    assert metrics["decode_tok_per_s_best"] is not None
    assert metrics["decode_tok_per_s_estimated"] is True
