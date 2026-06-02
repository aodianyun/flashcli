"""Unified Qwen NVFP4 RunEngine — ``--model qwen3|qwen36`` selects backend."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from flashcli.bundle.activate import active_bundle
from flashcli.engines.base import ChatMessage, ChatRequest
from flashcli.models.registry import Preset

from _qwen_util import run_async, serve_cfg, usage_from_qwen36_engine
from serve import ServeEngine


class RunEngine:
    def __init__(self) -> None:
        self._serve = ServeEngine()

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        self._serve.load(checkpoint, preset, **options)
        warm = options.get("warmup")
        if warm is None:
            bundle = active_bundle()
            if bundle is not None:
                variant = str(options.get("model") or options.get("variant") or "")
                warm = serve_cfg(bundle, variant or None).get("warmup")
        if warm:
            self._serve.warmup(str(warm))

    def predict(
        self,
        *,
        prompt: str = "",
        images: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del images
        if self._serve._backend is None:
            raise RuntimeError("RunEngine.load() not called")

        max_tokens = int(kwargs.get("max_tokens", 256))
        echo = bool(kwargs.get("echo", True))
        benchmark = int(kwargs.get("benchmark", 0))
        warmup_iters = int(kwargs.get("warmup_iters", 0))
        variant = self._serve._variant

        req = ChatRequest(
            messages=[
                ChatMessage(
                    role="user",
                    content=(prompt or "Hello!").strip() or "Hello!",
                )
            ],
            max_tokens=max_tokens,
            temperature=float(kwargs.get("temperature", 0.0)),
            top_p=float(kwargs.get("top_p", 1.0)),
            top_k=int(kwargs.get("top_k", 0)),
            seed=int(kwargs["seed"]) if kwargs.get("seed") is not None else None,
        )

        async def _one() -> dict[str, Any]:
            result = await self._serve.chat_async(req)
            usage = result.usage
            if variant == "qwen36":
                usage = usage_from_qwen36_engine(
                    {
                        **usage,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    }
                )
            return {
                "text": result.content or "",
                "tool_calls": result.tool_calls,
                "usage": usage,
                "finish_reason": result.finish_reason,
            }

        if warmup_iters > 0:
            for _ in range(warmup_iters):
                run_async(_one())

        if benchmark > 0:
            times: list[float] = []
            last: dict[str, Any] = {}
            for _ in range(benchmark):
                t0 = time.perf_counter()
                last = run_async(_one())
                times.append(time.perf_counter() - t0)
            if echo and times:
                mean_s = statistics.mean(times)
                tps = last.get("usage", {}).get("tok_per_s", 0)
                print(f"benchmark n={len(times)} mean={mean_s:.3f}s (last {tps} tok/s)")
            return last

        out = run_async(_one())
        if echo:
            print(out.get("text", ""))
        return out
