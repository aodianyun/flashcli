#!/usr/bin/env python3
"""Build OpenAI chat/completions JSON with a prompt of ~N tokens (for curl -d @file)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# FlashRT qwen36_nvfp4.md short standard prompt; repeated for long-ctx fills.
FLASHRT_DOC_SEED = (
    "Explain quantum entanglement in one short paragraph. "
)


def resolve_long_prompt_seed(style: str, seed_arg: str | None) -> str:
    key = (style or "repeat").lower()
    if seed_arg:
        return seed_arg
    if key in ("flashrt", "doc", "comparable"):
        return FLASHRT_DOC_SEED
    if key == "repeat":
        return "Explain one key idea of quantum mechanics in a single sentence."
    raise SystemExit(
        f"unknown --long-prompt-style {style!r}; use repeat, flashrt, or doc"
    )


def _seed_token_len(tokenizer, seed: str) -> int:
    return len(tokenizer.encode(seed, add_special_tokens=False))


def _tokens_per_repeat(tokenizer, seed: str, repeats: int) -> int:
    p = max(1, repeats)
    n = len(tokenizer.encode(seed * p, add_special_tokens=False))
    return max(1, (n + p - 1) // p)


def _effective_tokens_per_repeat(
    tokenizer, seed: str, *, budget: int = 0
) -> int:
    """Min tokens/repeat across short + long probes (BPE merges more at scale)."""
    probes = [128, 2048, 8192]
    if budget > 0:
        seed_len = _seed_token_len(tokenizer, seed)
        est = max(probes[-1], min(budget, (budget // max(1, seed_len)) // 2))
        if est not in probes:
            probes.append(est)
    return min(_tokens_per_repeat(tokenizer, seed, p) for p in probes)


def build_prompt_text(tokenizer, target_tokens: int, seed: str) -> tuple[str, int]:
    """Repeat *seed* text until encoded user length reaches *target_tokens*."""
    if target_tokens <= 0:
        return "", 0
    if _seed_token_len(tokenizer, seed) == 0:
        raise SystemExit("seed text tokenizes to empty sequence")

    tpr = _effective_tokens_per_repeat(tokenizer, seed, budget=target_tokens)
    reps = max(1, (target_tokens + tpr - 1) // tpr)
    lo, hi = max(1, reps - 4), reps + 4
    best_text, best_actual = seed * reps, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        text = seed * mid
        actual = len(tokenizer.encode(text, add_special_tokens=False))
        if actual <= target_tokens:
            best_text, best_actual = text, actual
            lo = mid + 1
        else:
            hi = mid - 1
    return best_text, best_actual


def rendered_prompt_tokens(tokenizer, user_content: str) -> int:
    """Match qwen36 ``_render_chat`` + ``tokenizer(prompt)`` (not tokenize=True)."""
    messages = [{"role": "user", "content": user_content}]
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            tools=None,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        input_ids = tokenizer(prompt, return_tensors="pt").input_ids
        return int(input_ids.shape[1])
    except Exception:
        return len(tokenizer.encode(user_content, add_special_tokens=False)) + 16


def _fit_log(msg: str) -> None:
    print(f"[bench-payload] {msg}", file=sys.stderr, flush=True)


def fit_user_prompt_to_budget(
    tokenizer,
    target_user_tokens: int,
    max_seq: int,
    max_tokens: int,
    seed: str,
    *,
    seq_slack: int = 32,
) -> tuple[str, int, int]:
    """Binary-search seed repeats so rendered chat prompt fits *max_seq*."""
    budget = int(max_seq) - int(max_tokens) - int(seq_slack)
    if budget < 1:
        raise SystemExit(
            f"max_seq={max_seq} too small for max_tokens={max_tokens} "
            f"seq_slack={seq_slack}"
        )

    seed_len = _seed_token_len(tokenizer, seed)
    if seed_len == 0:
        raise SystemExit("seed text tokenizes to empty sequence")

    tpr = _effective_tokens_per_repeat(tokenizer, seed, budget=budget)
    hi_reps = min(budget, (budget // tpr) + 128)
    if target_user_tokens > 0:
        hi_reps = min(hi_reps, (int(target_user_tokens) // tpr) + 128)
    want_fill_budget = target_user_tokens <= 0 or int(target_user_tokens) >= budget - 256

    _fit_log(
        f"fitting long prompt: rendered<={budget} "
        f"(max_seq={max_seq}, seed_once={seed_len}, eff_tok/repeat≈{tpr}, "
        f"max_repeats≈{hi_reps}) …"
    )

    def measure_reps(reps: int) -> tuple[int, str, int]:
        if reps <= 0:
            return 0, "", 0
        text = seed * reps
        user_n = len(tokenizer.encode(text, add_special_tokens=False))
        return rendered_prompt_tokens(tokenizer, text), text, user_n

    def binsearch(lo0: int, hi0: int) -> int:
        nonlocal best, step
        lo_reps, hi = lo0, hi0
        while lo_reps <= hi:
            mid = (lo_reps + hi) // 2
            step += 1
            if step == 1 or step % 4 == 0:
                _fit_log(f"  probe repeats={mid} (search {lo0}..{hi0}) …")
            rendered, text, user_n = measure_reps(mid)
            if rendered <= budget:
                best = (text, user_n, rendered)
                lo_reps = mid + 1
            else:
                hi = mid - 1
        return hi0

    best: tuple[str, int, int] = ("", 0, 0)
    step = 0
    binsearch(0, hi_reps)

    # If we hit the ceiling below budget, raise using observed tokens/repeat.
    while (
        want_fill_budget
        and best[0]
        and best[2] < budget - 16
        and hi_reps < budget
    ):
        best_reps = len(best[0]) // max(1, len(seed))
        tpr_obs = max(1, best[1] // max(1, best_reps))
        bump = max(256, (budget - best[2]) // tpr_obs + 64)
        new_hi = min(budget, hi_reps + bump)
        if new_hi <= hi_reps:
            break
        _fit_log(
            f"  raising ceiling {hi_reps} → {new_hi} "
            f"(rendered={best[2]} < budget, observed_tpr≈{tpr_obs}) …"
        )
        lo2 = hi_reps + 1
        hi_reps = new_hi
        binsearch(lo2, hi_reps)

    if not best[0]:
        raise SystemExit(
            f"cannot fit prompt within max_seq={max_seq} max_tokens={max_tokens}"
        )
    _fit_log(
        f"fit done: user_tokens={best[1]} rendered={best[2]} "
        f"(budget={budget}, steps={step})"
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
        "--long-prompt-style",
        choices=("repeat", "flashrt", "doc"),
        default="repeat",
        help="repeat=user --seed; flashrt/doc=FlashRT doc paragraph (better for MTP)",
    )
    p.add_argument(
        "--seed",
        default=None,
        help="Repeated fill text (overrides --long-prompt-style default)",
    )
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument(
        "--max-seq",
        type=int,
        default=0,
        help="If set, shrink user content so chat-template prompt + max_tokens fits",
    )
    p.add_argument(
        "--seq-slack",
        type=int,
        default=32,
        help="Safety margin below max-seq (template/tokenizer drift)",
    )
    p.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Set stream on chat/completions JSON (default: true)",
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
    seed = resolve_long_prompt_seed(args.long_prompt_style, args.seed)
    max_seq = int(args.max_seq or 0)
    if max_seq > 0:
        content, actual, rendered = fit_user_prompt_to_budget(
            tok,
            args.target_prompt_tokens,
            max_seq,
            args.max_tokens,
            seed,
            seq_slack=int(args.seq_slack),
        )
    else:
        content, actual = build_prompt_text(tok, args.target_prompt_tokens, seed)
        rendered = rendered_prompt_tokens(tok, content)
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": int(args.max_tokens),
        "temperature": float(args.temperature),
        "stream": bool(args.stream),
    }
    meta = {
        "long_prompt_style": args.long_prompt_style,
        "target_prompt_tokens": args.target_prompt_tokens,
        "actual_prompt_tokens": actual,
        "rendered_prompt_tokens": rendered,
        "max_tokens": payload["max_tokens"],
        "total_tokens_budget": rendered + int(args.max_tokens),
        "max_seq": max_seq if max_seq > 0 else None,
        "seq_slack": int(args.seq_slack) if max_seq > 0 else None,
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
