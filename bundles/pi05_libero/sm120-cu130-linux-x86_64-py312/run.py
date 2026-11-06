"""Pi0.5 LIBERO script entry — ``main(argv)``; standalone (no flashcli_bundle import)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _pi05_infer import load_pi05_model, run_pi05_predict

_DEFAULT_PROMPT = "pick up the red block and place it in the tray"


def _parse_bool_arg(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _image_paths_from_arg(raw: str | None) -> list[Path] | None:
    if not raw or not str(raw).strip():
        return None
    return [Path(part.strip()) for part in str(raw).split(",") if part.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pi0.5 LIBERO inference (script entry)")
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
        default=2,
        help="Number of camera views (LIBERO uses 2).",
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
        "--config",
        default="pi05",
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
    model = load_pi05_model(
        checkpoint,
        num_views=args.num_views,
        autotune=args.autotune,
        config=args.config,
        hardware=args.hardware,
        use_fp8=bool(args.use_fp8),
        framework=args.framework,
    )
    actions = run_pi05_predict(
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
