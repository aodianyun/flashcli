#!/usr/bin/env python3
"""One OpenAI chat/completions request with stream=true; emit bench metrics JSON."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    return json.loads(payload)


def run_stream(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    client_ttft_ms: float | None = None
    usage: dict[str, Any] = {}
    content_parts: list[str] = []
    finish_reason = "stop"
    chunks = 0
    content_chunks = 0

    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace")
                chunk = _parse_sse_line(line)
                if chunk is None:
                    continue
                chunks += 1
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    content_chunks += 1
                    if client_ttft_ms is None:
                        client_ttft_ms = (time.perf_counter() - t0) * 1000.0
                    content_parts.append(str(delta["content"]))
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
                if chunk.get("usage"):
                    usage = dict(chunk["usage"])
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {err_body}") from exc

    wall_ms = (time.perf_counter() - t0) * 1000.0
    if client_ttft_ms is None and content_parts:
        client_ttft_ms = wall_ms

    return {
        "id": "bench-stream",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
        "bench": {
            "stream": True,
            "wall_ms": wall_ms,
            "client_ttft_ms": client_ttft_ms,
            "sse_chunks": chunks,
            "sse_content_chunks": content_chunks,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--payload", type=argparse.FileType("r", encoding="utf-8"), required=True)
    p.add_argument("-o", "--output", required=True, help="Aggregated JSON (chat.completion shape)")
    args = p.parse_args()
    body = json.load(args.payload)
    if not body.get("stream"):
        raise SystemExit("payload stream=false; use curl for non-streaming")
    out = run_stream(args.url, body)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
        f.write("\n")
    bench = out.get("bench") or {}
    usage = out.get("usage") or {}
    print(
        json.dumps(
            {
                "wall_ms": bench.get("wall_ms"),
                "client_ttft_ms": bench.get("client_ttft_ms"),
                "server_ttft_ms": usage.get("ttft_ms") or usage.get("prefill_ms"),
                "tok_per_s": usage.get("tok_per_s")
                or usage.get("decode_tok_per_s")
                or usage.get("e2e_tok_per_s"),
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
