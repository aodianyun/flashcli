#!/usr/bin/env python3
"""Parse FlashRT qwen36_agent stream metric lines from serve.log (no FlashRT edits)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# service._fmt_metric_line joins with " | "; log line may have a logger prefix.
_STREAM_RE = re.compile(
    r"\bstream\s+\|.*?prefill=\s*([0-9.]+)\s+ttft=\s*([0-9.]+)\s+"
    r"decode=\s*([0-9.]+).*?\|\s*speed decode=\s*([0-9.]+)\s+tok/s",
)


def parse_stream_metrics(text: str) -> dict[str, Any] | None:
    matches = list(_STREAM_RE.finditer(text))
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
        "metrics_source": "serve_log",
    }


def read_since(path: Path, offset: int) -> str:
    with path.open("rb") as f:
        f.seek(max(0, offset))
        return f.read().decode("utf-8", errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("-o", "--output", type=Path, help="Write JSON metrics (stdout if omitted)")
    args = p.parse_args()
    if not args.log.is_file():
        print(json.dumps(None))
        return 1
    metrics = parse_stream_metrics(read_since(args.log, args.offset))
    out = json.dumps(metrics, ensure_ascii=False)
    if args.output:
        args.output.write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0 if metrics else 2


if __name__ == "__main__":
    raise SystemExit(main())
