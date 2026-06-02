#!/usr/bin/env python3
"""Parse engine timing lines from serve.log (FlashRT agent or HF baseline)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# FlashRT qwen36_agent service._fmt_metric_line (pipe-separated).
_FLASHRT_STREAM_RE = re.compile(
    r"\bstream\s+\|.*?prefill=\s*([0-9.]+)\s+ttft=\s*([0-9.]+)\s+"
    r"decode=\s*([0-9.]+).*?\|\s*speed decode=\s*([0-9.]+)\s+tok/s",
)

# bench_qwen36_hf_server.py stream done log line.
_HF_STREAM_DONE_RE = re.compile(
    r"stream done prompt=(\d+) completion=(\d+) prefill_ms=([0-9.]+) "
    r"decode_ms=([0-9.]+) decode_tok_per_s=([0-9.]+)"
)


def parse_flashrt_stream_metrics(text: str) -> dict[str, Any] | None:
    matches = list(_FLASHRT_STREAM_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    prefill_ms, ttft_ms, decode_ms, decode_tps = m.groups()
    return {
        "prefill_ms": float(prefill_ms),
        "first_delta_ms": float(ttft_ms),
        "ttft_ms": float(ttft_ms),
        "decode_ms": float(decode_ms),
        "decode_tok_per_s": float(decode_tps),
        "tok_per_s": float(decode_tps),
        "metrics_source": "serve_log_flashrt",
    }


def parse_hf_stream_metrics(text: str) -> dict[str, Any] | None:
    matches = list(_HF_STREAM_DONE_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    prompt_tok, completion, prefill_ms, decode_ms, decode_tps = m.groups()
    completion_n = int(completion)
    if completion_n <= 0:
        return None
    prefill = float(prefill_ms)
    return {
        "prompt_tokens": int(prompt_tok),
        "completion_tokens": completion_n,
        "prefill_ms": prefill,
        "first_delta_ms": prefill,
        "ttft_ms": prefill,
        "decode_ms": float(decode_ms),
        "decode_tok_per_s": float(decode_tps),
        "tok_per_s": float(decode_tps),
        "route": "hf_transformers",
        "metrics_source": "serve_log_hf",
    }


def parse_stream_metrics(text: str, *, backend: str = "auto") -> dict[str, Any] | None:
    if backend in ("auto", "flashrt"):
        m = parse_flashrt_stream_metrics(text)
        if m is not None:
            return m
    if backend in ("auto", "hf", "vllm"):
        m = parse_hf_stream_metrics(text)
        if m is not None:
            return m
    return None


def read_since(path: Path, offset: int) -> str:
    with path.open("rb") as f:
        f.seek(max(0, offset))
        return f.read().decode("utf-8", errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument(
        "--backend",
        choices=("auto", "flashrt", "hf", "vllm"),
        default="auto",
    )
    p.add_argument("-o", "--output", type=Path, help="Write JSON metrics (stdout if omitted)")
    args = p.parse_args()
    if not args.log.is_file():
        print(json.dumps(None))
        return 1
    metrics = parse_stream_metrics(read_since(args.log, args.offset), backend=args.backend)
    out = json.dumps(metrics, ensure_ascii=False)
    if args.output:
        args.output.write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0 if metrics else 2


if __name__ == "__main__":
    raise SystemExit(main())
