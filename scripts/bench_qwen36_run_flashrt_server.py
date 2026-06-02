#!/usr/bin/env python3
"""Run native FlashRT ``qwen36_agent`` HTTP server using the same bundle runtime as flashcli."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _flashcli_src() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


def _resolve_flashrt_repo(explicit: str | None) -> Path | None:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return root if (root / "serving" / "qwen36_agent").is_dir() else None
    script_root = Path(__file__).resolve().parents[1]
    for cand in (
        script_root.parent / "FlashRT",
        script_root / "FlashRT",
        Path(os.environ.get("FLASHRT_REPO", "")).expanduser(),
    ):
        if cand.is_dir() and (cand / "serving" / "qwen36_agent").is_dir():
            return cand.resolve()
    return None


def _import_server_main(flashrt_repo: Path | None):
    try:
        from flash_rt.serve.qwen36_agent.server import main as server_main

        return server_main
    except ImportError:
        pass
    if flashrt_repo is not None:
        serving = str(flashrt_repo / "serving")
        repo = str(flashrt_repo)
        for entry in (serving, repo):
            if entry not in sys.path:
                sys.path.insert(0, entry)
    from qwen36_agent.server import main as server_main

    return server_main


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, help="qwen_nvfp4 bundle root (flashcli-bundle.json)")
    p.add_argument("--checkpoint", required=True, help="Qwen3.6 NVFP4 checkpoint directory")
    p.add_argument("--mtp-checkpoint", default=None, help="MTP weights dir (mtp.safetensors)")
    p.add_argument("--flashrt-repo", default=None, help="FlashRT source tree (dev fallback)")
    p.add_argument("--model-name", default="qwen3.6-27b-nvfp4")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--max-seq", type=int, default=262208)
    p.add_argument("--route-min-seq", type=int, default=0)
    p.add_argument("--K", type=int, default=6, help="Default speculative K (maps to --default-K)")
    p.add_argument("--warmup-K", type=int, default=None, help="Warmup K (default: same as --K)")
    p.add_argument(
        "--warmup-preset",
        default="agent",
        help="Startup warmup preset: none, agent, short, long, all (match flashcli qwen36)",
    )
    p.add_argument("--warmup", default="", help='Extra warmup shapes, e.g. "128:64"')
    p.add_argument("--warmup-committed-max-prompt", type=int, default=1024)
    p.add_argument("--default-max-tokens", type=int, default=2048)
    p.add_argument("--max-output-tokens", type=int, default=16384)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default="info")
    args = p.parse_args()

    src = _flashcli_src()
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

    bundle_root = Path(args.bundle).expanduser().resolve()
    ckpt = Path(args.checkpoint).expanduser().resolve()
    if not ckpt.is_dir():
        raise SystemExit(f"checkpoint not found: {ckpt}")

    from flashcli.bundle.activate import activate_bundle
    from flashcli.bundle.manifest import load_bundle_manifest

    bundle = load_bundle_manifest(bundle_root)
    activate_bundle(bundle, install_python=False, quiet=True)

    mtp = args.mtp_checkpoint or os.environ.get("FLASHRT_QWEN36_MTP_CKPT_DIR")
    if mtp:
        os.environ["FLASHRT_QWEN36_MTP_CKPT_DIR"] = str(Path(mtp).expanduser().resolve())
    os.environ.setdefault("FLASHRT_QWEN36_LONG_KV_CACHE", "fp8")

    flashrt_repo = _resolve_flashrt_repo(args.flashrt_repo)
    server_main = _import_server_main(flashrt_repo)

    warmup_k = args.warmup_K if args.warmup_K is not None else args.K
    argv = [
        "--checkpoint",
        str(ckpt),
        "--model-name",
        args.model_name,
        "--device",
        args.device,
        "--max-seq",
        str(args.max_seq),
        "--route-min-seq",
        str(args.route_min_seq),
        "--default-K",
        str(args.K),
        "--warmup-K",
        str(warmup_k),
        "--warmup-preset",
        args.warmup_preset,
        "--warmup-committed-max-prompt",
        str(args.warmup_committed_max_prompt),
        "--default-max-tokens",
        str(args.default_max_tokens),
        "--max-output-tokens",
        str(args.max_output_tokens),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--log-level",
        args.log_level,
    ]
    if args.warmup.strip():
        argv.extend(["--warmup", args.warmup.strip()])

    server_main(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
