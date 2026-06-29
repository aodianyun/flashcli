"""Qwen3-VL NVFP4 RunEngine — independent from serve."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.preset import Preset

from _engine_qwen3_vl import Qwen3VlEngine
from _qwen3_vl_util import build_run_request, parse_warmup_spec, run_async


class RunEngine:
    def __init__(self) -> None:
        self._engine: Qwen3VlEngine | None = None
        self._run_defaults: dict[str, Any] = {}

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None:
        del preset
        bundle = active_bundle()
        if bundle is None:
            raise RuntimeError("No active bundle context")

        merged = dict(options)
        self._run_defaults = run_option_defaults(bundle)
        for key, default in self._run_defaults.items():
            merged.setdefault(key, default)

        max_pixels = merged.get("max_pixels")
        self._engine = Qwen3VlEngine(
            checkpoint=str(checkpoint.expanduser().resolve()),
            device=str(merged.get("device", "cuda:0")),
            model_name="qwen3-vl",
            max_seq=int(merged.get("max_seq", 2048)),
            max_q_seq=int(merged.get("max_q_seq", 1024)),
            max_pixels=int(max_pixels) if max_pixels is not None else None,
        )

        warm = merged.get("warmup")
        if warm:
            n = parse_warmup_spec(str(warm))
            if n > 0:
                self._engine.warmup(n)

    def predict(
        self,
        *,
        prompt: str = "",
        images: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._engine is None:
            raise RuntimeError("RunEngine.load() not called")

        merged = {"prompt": prompt, **kwargs}
        if images:
            merged["image"] = images[0] if isinstance(images[0], str) else str(images[0])

        d = self._run_defaults
        messages, gen_kw = build_run_request([], defaults=d, merged=merged)
        max_tokens = gen_kw.pop("max_tokens")
        benchmark = int(kwargs.get("benchmark", 0))
        warmup_iters = int(kwargs.get("warmup_iters", 0))
        echo = bool(kwargs.get("echo", True))

        async def _one() -> dict[str, Any]:
            content = ""
            tool_calls: list[dict[str, Any]] = []
            finish = "stop"
            usage: dict[str, Any] = {}
            async for ev in self._engine.stream_generate(
                messages,
                tools=None,
                max_tokens=max_tokens,
                stop=None,
                **gen_kw,
            ):
                if ev[0] == "content":
                    content += ev[1]
                elif ev[0] == "tool_calls":
                    tool_calls.extend(ev[1])
                elif ev[0] == "finish":
                    _, finish, usage = ev
            return {
                "text": content,
                "tool_calls": tool_calls,
                "usage": usage,
                "finish_reason": finish,
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
