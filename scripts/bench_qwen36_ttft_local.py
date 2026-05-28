#!/usr/bin/env python3
"""Measure true local TTFT for Qwen36 (prefill → first token), no HTTP/network.

Does not modify FlashRT sources. Replays the frontend prefill path used by
``flashcli serve``, then stops before the speculative decode loop.

Requires the same qwen_nvfp4 **bundle** as ``flashcli serve`` (native .so under
``lib/``). Use ``--bundle-dir`` or ``FLASHCLI_BUNDLE`` if not the default path.

Examples:

  export FLASHRT_QWEN36_MTP_CKPT_DIR=/path/to/fp8-mtp-ckpt
  export FLASHRT_QWEN36_LONG_KV_CACHE=fp8
  export FLASHRT_QWEN36_LONG_CTX_ROUTE_MIN_SEQ=512

  # Short prompt smoke (~19 rendered tokens; do not pass huge --max-seq for fit)
  python3 scripts/bench_qwen36_ttft_local.py \\
    --checkpoint ~/.flashcli/models/qwen36-27b-nvfp4/checkpoint \\
    --bundle-dir /path/to/qwen_nvfp4-runtime-bundle \\
    --K 6 --target-prompt-tokens 64 --long-prompt-style flashrt

  # 256K comparable (prefill only)
  python3 scripts/bench_qwen36_ttft_local.py \\
    --checkpoint ~/.flashcli/models/qwen36-27b-nvfp4/checkpoint \\
    --bundle-dir /path/to/qwen_nvfp4-runtime-bundle \\
    --max-seq 262208 --K 6 --target-prompt-tokens 262144 \\
    --long-prompt-style flashrt --skip-full-generate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_FLASHCLI_ROOT = Path(__file__).resolve().parents[1]
_FLASHCLI_SRC = _FLASHCLI_ROOT / "flashcli" / "src"
if _FLASHCLI_SRC.is_dir():
    sys.path.insert(0, str(_FLASHCLI_SRC))


def _default_bundle_dirs() -> list[Path]:
    roots = [_FLASHCLI_ROOT, _FLASHCLI_ROOT / "flashcli"]
    out: list[Path] = []
    for root in roots:
        cand = root / "bundles" / "qwen_nvfp4"
        if cand.is_dir():
            out.append(cand)
        # Installed / packed runtime (lib/*.so + flash_rt/)
        for name in ("runtime", "."):
            cand2 = root / "bundles" / "qwen_nvfp4" / name
            if (cand2 / "flashcli-bundle.json").is_file():
                out.append(cand2)
            elif name == "." and (cand / "flashcli-bundle.json").is_file():
                out.append(cand)
    # flashcli serve install layout
    home = Path(os.environ.get("HOME", ""))
    if home:
        for p in (
            home / ".flashcli" / "bundles" / "qwen36-27b-nvfp4",
            home / ".flashcli" / "bundles" / "qwen_nvfp4",
        ):
            if (p / "flashcli-bundle.json").is_file():
                out.append(p)
    return out


def _resolve_bundle_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not (root / "flashcli-bundle.json").is_file():
            raise SystemExit(f"bundle missing flashcli-bundle.json: {root}")
        return root
    env = os.environ.get("FLASHCLI_BUNDLE") or os.environ.get("QWEN_NVFP4_BUNDLE")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / "flashcli-bundle.json").is_file():
            raise SystemExit(f"FLASHCLI_BUNDLE invalid: {root}")
        return root
    for cand in _default_bundle_dirs():
        if (cand / "flashcli-bundle.json").is_file():
            return cand.resolve()
    raise SystemExit(
        "Cannot find qwen_nvfp4 bundle (need lib/flash_rt_kernels*.so). "
        "Set --bundle-dir or FLASHCLI_BUNDLE to the same runtime used by "
        "'flashcli serve qwen36-27b-nvfp4'."
    )


def _activate_bundle(bundle_root: Path) -> None:
    from flashcli.bundle.activate import activate_bundle
    from flashcli.bundle.manifest import load_bundle_manifest

    bundle = load_bundle_manifest(bundle_root)
    activate_bundle(
        bundle,
        profile="serve",
        install_python=False,
        quiet=True,
        force_python=False,
    )
    print(f"[ttft-local] bundle={bundle_root}", file=sys.stderr, flush=True)


def _load_engine(ckpt: Path, *, max_seq: int, K: int, device: str):
    from _flashrt_serve import import_qwen36_engine_class

    EngineCls = import_qwen36_engine_class()
    return EngineCls(
        checkpoint=str(ckpt),
        K=K,
        max_seq=max_seq,
        device=device,
        model_name="qwen36-27b-nvfp4",
    )


def _build_messages(args: argparse.Namespace) -> list[dict]:
    if args.payload and args.payload.is_file():
        body = json.loads(args.payload.read_text(encoding="utf-8"))
        return list(body["messages"])

    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import bench_qwen_make_payload as bmp

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(args.checkpoint), trust_remote_code=True)
    seed = bmp.resolve_long_prompt_seed(args.long_prompt_style, args.seed)
    fit_max_seq = int(args.fit_max_seq or 0)
    if fit_max_seq > 0:
        content, _actual, _rendered = bmp.fit_user_prompt_to_budget(
            tok,
            args.target_prompt_tokens,
            fit_max_seq,
            args.max_tokens,
            seed,
            seq_slack=args.seq_slack,
        )
    else:
        content, _actual = bmp.build_prompt_text(
            tok, args.target_prompt_tokens, seed
        )
    return [{"role": "user", "content": content}]


async def _run_full_generate(engine, messages, max_tokens: int) -> dict:
    import time

    t0 = time.perf_counter()
    data = await engine.generate(messages, None, max_tokens)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "wall_ms": wall_ms,
        "prefill_ms": float(data.get("prefill_ms") or 0.0),
        "decode_ms": float(data.get("decode_ms") or 0.0),
        "decode_tok_per_s": float(data.get("decode_tok_per_s") or 0.0),
        "route": data.get("route"),
        "prompt_tokens": int(data.get("prompt_tokens") or 0),
        "completion_tokens": int(data.get("completion_tokens") or 0),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument(
        "--bundle-dir",
        type=Path,
        default=None,
        help="qwen_nvfp4 bundle root (flashcli-bundle.json + lib/*.so)",
    )
    p.add_argument(
        "--max-seq",
        type=int,
        default=262208,
        help="Engine max_seq (not used for prompt fit unless --fit-max-seq)",
    )
    p.add_argument(
        "--fit-max-seq",
        type=int,
        default=0,
        help="If set, fit long prompt to this max_seq (use 262208 for 256K)",
    )
    p.add_argument("--max-tokens", type=int, default=64)
    p.add_argument("--K", type=int, default=6)
    p.add_argument("--device", default="cuda:0")
    p.add_argument(
        "--target-prompt-tokens",
        type=int,
        default=64,
        help="User message token target (262144 for 256K comparable)",
    )
    p.add_argument(
        "--long-prompt-style",
        choices=("repeat", "flashrt", "doc"),
        default="flashrt",
    )
    p.add_argument("--seed", default=None)
    p.add_argument("--seq-slack", type=int, default=32)
    p.add_argument(
        "-p",
        "--payload",
        type=Path,
        help="Reuse messages from a chat/completions JSON file",
    )
    p.add_argument(
        "--skip-full-generate",
        action="store_true",
        help="Only prefill probe (faster for 256K; no decode comparison)",
    )
    args = p.parse_args()

    ckpt = args.checkpoint.expanduser().resolve()
    if not ckpt.is_dir():
        raise SystemExit(f"checkpoint not found: {ckpt}")

    bundle_root = _resolve_bundle_dir(args.bundle_dir)
    _activate_bundle(bundle_root)

    # activate_bundle prepends bundle_root; ensure helpers import.
    br = str(bundle_root)
    if br not in sys.path:
        sys.path.insert(0, br)

    print("[ttft-local] building prompt …", file=sys.stderr, flush=True)
    messages = _build_messages(args)

    print("[ttft-local] loading engine …", file=sys.stderr, flush=True)
    engine = _load_engine(ckpt, max_seq=args.max_seq, K=args.K, device=args.device)

    input_ids = engine.prepare_request(messages, None, args.max_tokens).cuda()
    prompt_len = int(input_ids.shape[1])
    print(f"[ttft-local] rendered prompt_tokens≈{prompt_len}", file=sys.stderr, flush=True)

    from _qwen36_ttft import measure_prefill_ttft

    print(
        "[ttft-local] prefill probe (stops before decode loop) …",
        file=sys.stderr,
        flush=True,
    )
    probe = measure_prefill_ttft(
        engine.fe,
        input_ids,
        max_new_tokens=args.max_tokens,
        K=args.K,
    )

    out: dict = {"prefill_probe": probe, "bundle_dir": str(bundle_root)}
    if not args.skip_full_generate:
        print(
            "[ttft-local] full generate (compare usage.prefill_ms) …",
            file=sys.stderr,
            flush=True,
        )
        full = asyncio.run(_run_full_generate(engine, messages, args.max_tokens))
        out["full_generate"] = full
        out["delta_ms"] = {
            "wall_minus_prefill": full["wall_ms"] - full["prefill_ms"],
            "probe_minus_usage_prefill": probe["engine_prefill_ms"] - full["prefill_ms"],
        }

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(
        f"\n[ttft-local] true TTFT ≈ engine_prefill_ms "
        f"({probe['engine_prefill_ms']:.1f} ms), route={probe['route']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
