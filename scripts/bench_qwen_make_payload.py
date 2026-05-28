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


def rendered_prompt_tokens(tokenizer, user_content: str) -> int:
    """Tokens after chat template + generation prompt (matches HTTP serve path)."""
    messages = [{"role": "user", "content": user_content}]
    try:
        ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
        )
        return len(ids)
    except Exception:
        # Fallback if template unavailable.
        return len(tokenizer.encode(user_content, add_special_tokens=False)) + 16


def fit_user_prompt_to_budget(
    tokenizer,
    target_user_tokens: int,
    max_seq: int,
    max_tokens: int,
    seed: str,
) -> tuple[str, int, int]:
    """Binary-search user message length so rendered prompt + max_tokens <= max_seq."""
    budget = int(max_seq) - int(max_tokens)
    if budget < 1:
        raise SystemExit(
            f"max_seq={max_seq} too small for max_tokens={max_tokens}"
        )
    text, user_n = build_prompt_text(tokenizer, target_user_tokens, seed)
    rendered = rendered_prompt_tokens(tokenizer, text)
    if rendered <= budget:
        return text, user_n, rendered
    lo, hi = 0, int(target_user_tokens)
    best: tuple[str, int, int] = ("", 0, 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        text, user_n = build_prompt_text(tokenizer, mid, seed)
        rendered = rendered_prompt_tokens(tokenizer, text)
        if rendered <= budget:
            best = (text, user_n, rendered)
            lo = mid + 1
        else:
            hi = mid - 1
    if not best[0]:
        raise SystemExit(
            f"cannot fit prompt within max_seq={max_seq} max_tokens={max_tokens}"
        )
    return best


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
    p.add_argument(
        "--max-seq",
        type=int,
        default=0,
        help="If set, shrink user content so chat-template prompt + max_tokens fits",
    )
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
    max_seq = int(args.max_seq or 0)
    if max_seq > 0:
        content, actual, rendered = fit_user_prompt_to_budget(
            tok,
            args.target_prompt_tokens,
            max_seq,
            args.max_tokens,
            args.seed,
        )
    else:
        content, actual = build_prompt_text(tok, args.target_prompt_tokens, args.seed)
        rendered = rendered_prompt_tokens(tok, content)
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
        "rendered_prompt_tokens": rendered,
        "max_tokens": payload["max_tokens"],
        "total_tokens_budget": rendered + int(args.max_tokens),
        "max_seq": max_seq if max_seq > 0 else None,
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
