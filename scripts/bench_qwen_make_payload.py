#!/usr/bin/env python3
"""Build OpenAI chat/completions JSON with a prompt of ~N tokens (for curl -d @file)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_prompt_text(tokenizer, target_tokens: int, seed: str) -> tuple[str, int]:
    seed_ids = tokenizer.encode(seed, add_special_tokens=False)
    if not seed_ids:
        raise SystemExit("seed text tokenizes to empty sequence")
    ids: list[int] = []
    while len(ids) < target_tokens:
        ids.extend(seed_ids)
    ids = ids[:target_tokens]
    text = tokenizer.decode(ids, skip_special_tokens=True)
    actual = len(tokenizer.encode(text, add_special_tokens=False))
    return text, actual


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--checkpoint",
        type=Path,
        required=True,
        help="HF weights dir (for tokenizer only)",
    )
    p.add_argument("--model", required=True, help="model id in JSON body")
    p.add_argument(
        "--target-prompt-tokens",
        type=int,
        default=64,
        help="Approximate user message length in tokens",
    )
    p.add_argument("--max-tokens", type=int, default=64)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument(
        "--seed",
        default="请用一句话说明量子力学的一个要点。",
        help="Repeated to fill long prompts",
    )
    p.add_argument("-o", "--output", type=Path, required=True)
    args = p.parse_args()

    ckpt = args.checkpoint.expanduser().resolve()
    if not ckpt.is_dir():
        raise SystemExit(f"checkpoint not found: {ckpt}")

    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "transformers required: pip install transformers"
        ) from exc

    tok = AutoTokenizer.from_pretrained(str(ckpt), trust_remote_code=True)
    content, actual = build_prompt_text(tok, args.target_prompt_tokens, args.seed)
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": int(args.max_tokens),
        "temperature": float(args.temperature),
        "stream": False,
    }
    meta = {
        "target_prompt_tokens": args.target_prompt_tokens,
        "actual_prompt_tokens": actual,
        "max_tokens": payload["max_tokens"],
        "content_chars": len(content),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(meta, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
