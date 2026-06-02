#!/usr/bin/env python3
"""Token metadata for HTTP bench payloads (context + max output)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import bench_qwen_make_payload as bmp  # noqa: E402


def describe_payload(
    payload_path: Path,
    *,
    checkpoint: Path | None = None,
    case: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    messages = payload.get("messages") or []
    content = ""
    if messages and isinstance(messages[0], dict):
        content = str(messages[0].get("content") or "")

    max_out = int(payload.get("max_tokens") or 0)
    meta: dict[str, Any] = {
        "case": case or payload_path.stem,
        "payload_file": payload_path.name,
        "max_output_tokens": max_out,
        "user_tokens": None,
        "rendered_prompt_tokens": None,
        "total_tokens_budget": None,
    }
    if extra:
        meta.update(extra)

    if checkpoint is not None and checkpoint.is_dir():
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise SystemExit(
                "transformers required for payload token metadata"
            ) from exc
        tok = AutoTokenizer.from_pretrained(str(checkpoint), trust_remote_code=True)
        meta["user_tokens"] = len(tok.encode(content, add_special_tokens=False))
        meta["rendered_prompt_tokens"] = bmp.rendered_prompt_tokens(tok, content)
        meta["total_tokens_budget"] = int(meta["rendered_prompt_tokens"]) + max_out

    return meta


def write_manifest(manifest_path: Path, meta_dir: Path) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for path in sorted(meta_dir.glob("*.meta.json")):
        stem = path.name[: -len(".meta.json")]
        cases[stem] = json.loads(path.read_text(encoding="utf-8"))
    doc = {"cases": cases}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return doc


def format_case_tokens(meta: dict[str, Any]) -> str:
    ctx = meta.get("rendered_prompt_tokens")
    out = meta.get("max_output_tokens")
    if ctx is None and out is None:
        return "ctx=? out=?"
    ctx_s = str(int(ctx)) if ctx is not None else "?"
    out_s = str(int(out)) if out is not None else "?"
    return f"ctx={ctx_s} out={out_s}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--payload", type=Path, required=True, help="OpenAI chat payload JSON")
    p.add_argument("--checkpoint", type=Path, default=None, help="HF weights for tokenizer")
    p.add_argument("--case", default=None, help="Case stem (default: payload stem)")
    p.add_argument("--meta-output", type=Path, default=None, help="Write per-case .meta.json")
    p.add_argument(
        "--merge-manifest",
        type=Path,
        default=None,
        help="Rebuild payloads/manifest.json from *.meta.json in this directory",
    )
    p.add_argument(
        "--extra-json",
        default=None,
        help="JSON object merged into meta (e.g. fit metadata from make_payload)",
    )
    args = p.parse_args()

    extra = json.loads(args.extra_json) if args.extra_json else None
    ckpt = args.checkpoint.expanduser().resolve() if args.checkpoint else None
    meta = describe_payload(
        args.payload.expanduser().resolve(),
        checkpoint=ckpt,
        case=args.case,
        extra=extra,
    )

    if args.meta_output is not None:
        out = args.meta_output.expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.merge_manifest is not None:
        write_manifest(args.merge_manifest.expanduser().resolve(), args.payload.parent)

    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
