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

# Optional legacy / third-party stream done log line.
_HF_STREAM_DONE_RE = re.compile(
    r"stream done prompt=(\d+) completion=(\d+) prefill_ms=([0-9.]+) "
    r"decode_ms=([0-9.]+) decode_tok_per_s=([0-9.]+)"
)


def _flashrt_metrics_from_match(line: str, m: re.Match[str]) -> dict[str, Any]:
    prefill_ms, ttft_ms, decode_ms, decode_tps = m.groups()
    out: dict[str, Any] = {
        "prefill_ms": float(prefill_ms),
        "first_delta_ms": float(ttft_ms),
        "ttft_ms": float(ttft_ms),
        "decode_ms": float(decode_ms),
        "decode_tok_per_s": float(decode_tps),
        "tok_per_s": float(decode_tps),
        "metrics_source": "serve_log_flashrt",
    }
    tok_m = re.search(r"\bout=(\d+)\b", line)
    if tok_m:
        out["completion_tokens"] = int(tok_m.group(1))
    prompt_m = re.search(r"\bp=(\d+)\b", line)
    if prompt_m:
        out["prompt_tokens"] = int(prompt_m.group(1))
    return out


def parse_flashrt_stream_metrics(text: str) -> dict[str, Any] | None:
    matches = list(_FLASHRT_STREAM_RE.finditer(text))
    if not matches:
        return None
    return _flashrt_metrics_from_match(text, matches[-1])


def iter_flashrt_stream_metrics(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "stream |" not in line:
            continue
        m = _FLASHRT_STREAM_RE.search(line)
        if m is not None:
            out.append(_flashrt_metrics_from_match(line, m))
    return out


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


def iter_stream_metrics(text: str, *, backend: str = "auto") -> list[dict[str, Any]]:
    """All engine timing records in log order (one per completed stream request)."""
    if backend in ("auto", "flashrt"):
        flashrt = iter_flashrt_stream_metrics(text)
        if flashrt:
            return flashrt
        if backend == "flashrt":
            return []
    if backend in ("auto", "hf", "vllm"):
        out: list[dict[str, Any]] = []
        for line in text.splitlines():
            m = _HF_STREAM_DONE_RE.search(line)
            if not m:
                continue
            block = line[m.start() :]
            parsed = parse_hf_stream_metrics(block)
            if parsed is not None:
                out.append(parsed)
        return out
    return []


BENCH_CASE_ORDER = ("qwen3_short", "qwen36_short", "qwen3_long", "qwen36_long")


def merge_metrics_into_row(row: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    usage = dict(row.get("usage") or {})
    bench = dict(row.get("bench") or {})
    src = metrics.get("metrics_source")
    for key, val in metrics.items():
        if key == "metrics_source" or val is None:
            continue
        usage[key] = val
    ttft = metrics.get("ttft_ms") or metrics.get("first_delta_ms")
    if ttft is not None:
        bench["server_ttft_ms"] = float(ttft)
        bench["ttft_ms"] = float(ttft)
        bench["ttft_source"] = "engine"
    if src:
        bench["metrics_source"] = src
    row["usage"] = usage
    row["bench"] = bench
    return row


def rehydrate_workdir(
    workdir: Path,
    log_path: Path,
    *,
    backend: str = "auto",
) -> int:
    """Fill engine TTFT/decode into *.metrics.jsonl from serve.log (in bench case order)."""
    if not log_path.is_file():
        return 0
    text = log_path.read_text(encoding="utf-8", errors="replace")
    engine_rows = iter_stream_metrics(text, backend=backend)
    if not engine_rows:
        return 0

    jsonl_files = [
        workdir / f"{stem}.metrics.jsonl"
        for stem in BENCH_CASE_ORDER
        if (workdir / f"{stem}.metrics.jsonl").is_file()
    ]
    if not jsonl_files:
        jsonl_files = sorted(workdir.glob("*.metrics.jsonl"))
    idx = 0
    updated = 0
    for jsonl_path in jsonl_files:
        lines = [
            ln.strip()
            for ln in jsonl_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        new_lines: list[str] = []
        for line in lines:
            row = json.loads(line)
            if idx < len(engine_rows):
                merge_metrics_into_row(row, engine_rows[idx])
                updated += 1
                idx += 1
            new_lines.append(json.dumps(row, ensure_ascii=False))
        jsonl_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def read_since(path: Path, offset: int) -> str:
    with path.open("rb") as f:
        f.seek(max(0, offset))
        return f.read().decode("utf-8", errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, help="serve.log path")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument(
        "--backend",
        choices=("auto", "flashrt", "hf", "vllm"),
        default="auto",
    )
    p.add_argument(
        "--rehydrate-workdir",
        type=Path,
        metavar="DIR",
        help="Merge all stream| lines from --log into DIR/*.metrics.jsonl (bench order)",
    )
    p.add_argument("-o", "--output", type=Path, help="Write JSON metrics (stdout if omitted)")
    args = p.parse_args()

    if args.rehydrate_workdir is not None:
        if args.log is None:
            p.error("--rehydrate-workdir requires --log")
        n = rehydrate_workdir(
            args.rehydrate_workdir.expanduser().resolve(),
            args.log.expanduser().resolve(),
            backend=args.backend,
        )
        print(json.dumps({"updated_rows": n, "workdir": str(args.rehydrate_workdir)}))
        return 0 if n > 0 else 2

    if args.log is None:
        p.error("--log is required unless using --rehydrate-workdir")
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
