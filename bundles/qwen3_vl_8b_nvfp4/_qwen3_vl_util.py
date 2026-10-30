"""Shared helpers for Qwen3-VL NVFP4 bundle."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.options import option_value, run_option_defaults, serve_option_defaults
from flashcli_bundle.protocol import ChatMessage, ChatRequest

from _qwen3_vl_util_messages import (
    DEFAULT_VL_PROCESSOR_REPOS,
    messages_from_request,
    openai_messages_to_frontend,
    run_messages_from_prompt,
)


def vl_processor_fallback_repos(bundle: BundleManifest | None = None) -> tuple[str, ...]:
    """Repos to load VL processor sidecars when the NVFP4 checkpoint omits them."""
    import os

    repos: list[str] = []
    env_repo = os.environ.get("QWEN3_VL_PROCESSOR_REPO")
    if env_repo:
        repos.append(env_repo.strip())
    if bundle is not None:
        weights = bundle.raw.get("weights")
        if isinstance(weights, dict):
            proc_repo = weights.get("processor_repo")
            if proc_repo:
                repos.append(str(proc_repo))
    repos.extend(DEFAULT_VL_PROCESSOR_REPOS)
    seen: set[str] = set()
    out: list[str] = []
    for repo in repos:
        if repo and repo not in seen:
            seen.add(repo)
            out.append(repo)
    return tuple(out)


def merge_load_options(bundle: BundleManifest, **options: Any) -> dict[str, Any]:
    merged = serve_option_defaults(bundle)
    merged.update({k: v for k, v in options.items() if v is not None})
    return merged


def run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "Cannot run async Qwen3-VL engine from an active event loop; "
        "await chat_async() / chat_stream_async() instead."
    )


def parse_warmup_spec(spec: str | None) -> int:
    if not spec or not str(spec).strip():
        return 0
    text = str(spec).strip()
    if ":" in text:
        text = text.split(",")[0].split(":")[-1]
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def resolve_warmup_tokens(
    *,
    preset: str | None,
    extra_spec: str | None,
    bundle_default: str | None,
) -> int:
    key = (preset or "none").lower()
    if key in ("none", "off", "false", "0"):
        base = 0
    elif key == "short":
        base = 32
    else:
        base = 0
    extra = parse_warmup_spec(extra_spec) or parse_warmup_spec(bundle_default)
    return max(base, extra)


def build_run_request(
    req_messages: list[ChatMessage],
    *,
    defaults: dict[str, Any],
    merged: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del req_messages
    d = {
        "max_tokens": 256,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        **defaults,
    }
    prompt = str(option_value("prompt", merged, d) or "")
    image = option_value("image", merged, d)
    messages = run_messages_from_prompt(
        prompt,
        image_path=str(image) if image else None,
    )
    seed = option_value("seed", merged, d)
    gen_kw = {
        "max_tokens": int(option_value("max_tokens", merged, d)),
        "temperature": float(option_value("temperature", merged, d)),
        "top_p": float(option_value("top_p", merged, d)),
        "top_k": int(option_value("top_k", merged, d)),
        "seed": int(seed) if seed is not None else None,
    }
    return messages, gen_kw


def chat_request_to_frontend(req: ChatRequest) -> list[dict[str, Any]]:
    oai = messages_from_request(req)
    return openai_messages_to_frontend(oai)
