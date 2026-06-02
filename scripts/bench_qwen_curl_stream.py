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


def _merge_flashrt_into_usage(usage: dict[str, Any], flashrt: dict[str, Any]) -> None:
    """Promote top-level ``flashrt`` timing into ``usage`` without overwriting tokens."""
    for key in (
        "prefill_ms",
        "decode_ms",
        "first_delta_ms",
        "ttft_ms",
        "decode_tok_per_s",
        "e2e_tok_per_s",
        "tok_per_s",
        "route",
        "cached_tokens",
        "session_id",
        "prefix_action",
    ):
        if usage.get(key) is None and flashrt.get(key) is not None:
            usage[key] = flashrt[key]
    if usage.get("ttft_ms") is None and usage.get("first_delta_ms") is not None:
        usage["ttft_ms"] = usage["first_delta_ms"]


def _server_ttft_ms(usage: dict[str, Any]) -> float | None:
    """Engine TTFT: first token latency, not full prefill wall."""
    for key in ("ttft_ms", "first_delta_ms"):
        val = usage.get(key)
        if val is not None:
            return float(val)
    return None


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
                flashrt = chunk.get("flashrt")
                if isinstance(flashrt, dict):
                    _merge_flashrt_into_usage(usage, flashrt)
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    content_chunks += 1
                    if client_ttft_ms is None:
                        client_ttft_ms = (time.perf_counter() - t0) * 1000.0
                    content_parts.append(str(content))
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
                if chunk.get("usage"):
                    usage = dict(chunk["usage"])
                    if isinstance(flashrt, dict):
                        _merge_flashrt_into_usage(usage, flashrt)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {err_body}") from exc

    wall_ms = (time.perf_counter() - t0) * 1000.0
    if client_ttft_ms is None and content_parts:
        client_ttft_ms = wall_ms

    server_ttft = _server_ttft_ms(usage)
    if not usage.get("tok_per_s") and not usage.get("decode_tok_per_s"):
        ct = usage.get("completion_tokens")
        if ct is None and content_parts:
            ct = len(content_parts)
            usage["completion_tokens"] = ct
        if ct is not None:
            decode_ms = usage.get("decode_ms")
            if decode_ms is None:
                ttft_for_decode = server_ttft if server_ttft is not None else client_ttft_ms
                decode_ms = wall_ms
                if ttft_for_decode is not None:
                    decode_ms = max(1.0, wall_ms - float(ttft_for_decode))
            if decode_ms and float(decode_ms) > 0:
                tps = float(ct) * 1000.0 / float(decode_ms)
                usage.setdefault("decode_tok_per_s", tps)
                usage.setdefault("tok_per_s", tps)

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
            "server_ttft_ms": server_ttft,
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
                "server_ttft_ms": bench.get("server_ttft_ms"),
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
