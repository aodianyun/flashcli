"""GROOT N1.7 script entry — ``main(argv)``; standalone (no flashcli_bundle import)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _groot_infer import load_groot_model, preprocess_groot_n17, run_groot_infer_n17

_DEFAULT_PROMPT = "put the blue block in the green bowl"
_DEFAULT_EMBODIMENT = "oxe_droid_relative_eef_relative_joint"


def _parse_bool_arg(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _image_paths_from_arg(raw: str | None) -> list[Path] | None:
    if not raw or not str(raw).strip():
        return None
    return [Path(part.strip()) for part in str(raw).split(",") if part.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GROOT N1.7 inference (script entry)")
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
        "--state",
        default=None,
        help="Optional .npz with state.* arrays for normalization / relative-action decode.",
    )
    parser.add_argument(
        "--num-views",
        type=int,
        default=2,
        help="Number of camera views (oxe_droid_relative_eef_relative_joint uses 2).",
    )
    parser.add_argument(
        "--embodiment-tag",
        default=_DEFAULT_EMBODIMENT,
        help="GROOT N1.7 embodiment slot.",
    )
    parser.add_argument(
        "--action-horizon",
        type=int,
        default=40,
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
        default="groot_n17",
        help="FlashRT model config name.",
    )
    parser.add_argument(
        "--framework",
        default="torch",
        help="FlashRT framework backend.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for Gr00tPolicy aux capture (diffusion noise).",
    )
    parser.add_argument(
        "--benchmark",
        type=int,
        default=0,
        help="Timed infer iterations after warmup (0 disables).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="Extra infer iterations before --benchmark.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Less output (suppress benchmark summary).",
    )
    return parser


def _format_actions(actions: object) -> str:
    if isinstance(actions, dict):
        parts = []
        for key, value in actions.items():
            shape = getattr(value, "shape", type(value).__name__)
            parts.append(f"{key}={shape}")
        return "{" + ", ".join(parts) + "}"
    shape = getattr(actions, "shape", type(actions).__name__)
    return f"shape={shape}"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])

    ckpt_raw = os.environ.get("FLASHCLI_CHECKPOINT", "").strip()
    if not ckpt_raw:
        print("FLASHCLI_CHECKPOINT is not set (run via flashcli run)", file=sys.stderr)
        return 1
    checkpoint = Path(ckpt_raw)

    args = _build_parser().parse_args(argv)
    aux, state_dict = preprocess_groot_n17(
        checkpoint,
        prompt=args.prompt,
        embodiment_tag=args.embodiment_tag,
        num_views=args.num_views,
        image_paths=_image_paths_from_arg(args.image),
        state_path=args.state,
        seed=args.seed,
    )
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
    actions = run_groot_infer_n17(
        model,
        aux,
        state_dict,
        prompt=args.prompt,
        action_horizon=args.action_horizon,
        warmup=args.warmup,
        benchmark=args.benchmark,
        quiet=args.quiet,
    )
    print(f"actions: {_format_actions(actions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
