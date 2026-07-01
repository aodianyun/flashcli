"""GROOT N1.6 script entry — ``main(argv)``; standalone (no flashcli_bundle import)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _groot_infer import load_groot_model, run_groot_predict

_DEFAULT_PROMPT = "pick up the cup on the table"
_DEFAULT_EMBODIMENT = "gr1"


def _parse_bool_arg(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _image_paths_from_arg(raw: str | None) -> list[Path] | None:
    if not raw or not str(raw).strip():
        return None
    return [Path(part.strip()) for part in str(raw).split(",") if part.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GROOT N1.6 inference (script entry)")
    parser.add_argument(
        "--prompt",
        default=_DEFAULT_PROMPT,
        help="Natural-language task instruction.",
    )
    parser.add_argument(
        "--image",
        default=None,
        help="Comma-separated RGB image paths (one per camera view).",
    )
    parser.add_argument(
        "--num-views",
        type=int,
        default=1,
        help="Number of camera views (gr1 uses 1).",
    )
    parser.add_argument(
        "--embodiment-tag",
        default=_DEFAULT_EMBODIMENT,
        help="GROOT embodiment slot (gr1, robocasa_panda_omron, behavior_r1_pro).",
    )
    parser.add_argument(
        "--action-horizon",
        type=int,
        default=16,
        help="Number of action steps to generate.",
    )
    parser.add_argument(
        "--hardware",
        default="auto",
        help="FlashRT backend: auto, rtx_sm89, rtx_sm120, thor.",
    )
    parser.add_argument(
        "--autotune",
        type=int,
        default=3,
        help="CUDA graph autotune trials (0 disables).",
    )
    parser.add_argument(
        "--use-fp8",
        type=_parse_bool_arg,
        nargs="?",
        const=True,
        default=True,
        help="Load policy weights in FP8 when supported.",
    )
    parser.add_argument(
        "--use-fp16",
        type=_parse_bool_arg,
        nargs="?",
        const=True,
        default=False,
        help="Run full-FP16 baseline (disables FP8).",
    )
    parser.add_argument(
        "--config",
        default="groot",
        help="FlashRT model config name.",
    )
    parser.add_argument(
        "--framework",
        default="torch",
        help="FlashRT framework backend.",
    )
    parser.add_argument(
        "--benchmark",
        type=int,
        default=0,
        help="Timed predict iterations after warmup (0 disables).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="Extra predict iterations before --benchmark.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Less output (suppress benchmark summary).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    ckpt_raw = os.environ.get("FLASHCLI_CHECKPOINT", "").strip()
    if not ckpt_raw:
        print("FLASHCLI_CHECKPOINT is not set (run via flashcli run)", file=sys.stderr)
        return 1
    checkpoint = Path(ckpt_raw)

    args = _build_parser().parse_args(argv)
    model = load_groot_model(
        checkpoint,
        num_views=args.num_views,
        embodiment_tag=args.embodiment_tag,
        action_horizon=args.action_horizon,
        autotune=args.autotune,
        config=args.config,
        hardware=args.hardware,
        use_fp8=bool(args.use_fp8),
        use_fp16=bool(args.use_fp16),
        framework=args.framework,
    )
    actions = run_groot_predict(
        model,
        prompt=args.prompt,
        num_views=args.num_views,
        image_paths=_image_paths_from_arg(args.image),
        warmup=args.warmup,
        benchmark=args.benchmark,
        quiet=args.quiet,
    )
    print(f"actions: shape={getattr(actions, 'shape', type(actions).__name__)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
