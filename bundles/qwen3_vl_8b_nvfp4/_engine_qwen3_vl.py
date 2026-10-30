"""Qwen3-VL inference engine (bundle-local; no FlashRT modifications)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from _qwen3_vl_frontend import Qwen3VlFrontend
from _qwen3_vl_stream_parser import StreamParser, sample_token

log = logging.getLogger(__name__)


def _dummy_warmup_messages() -> list[dict[str, Any]]:
    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(128, 128, 128))
    return [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": img},
                {"type": "text", "text": "warmup"},
            ],
        }
    ]


class Qwen3VlEngine:
    """Async multimodal engine with true token streaming and tool-call parsing."""

    def __init__(
        self,
        *,
        checkpoint: str,
        device: str,
        model_name: str,
        max_seq: int,
        max_q_seq: int,
        max_pixels: int | None,
        processor_fallback_repos: tuple[str, ...] | None = None,
    ) -> None:
        log.info("loading Qwen3-VL NVFP4 ckpt from %s ...", checkpoint)
        t0 = time.perf_counter()
        self.fe = Qwen3VlFrontend(
            checkpoint,
            device=device,
            max_seq=int(max_seq),
            max_q_seq=int(max_q_seq),
            max_pixels=max_pixels,
            processor_fallback_repos=processor_fallback_repos,
        )
        log.info("loaded in %.1f s", time.perf_counter() - t0)
        self.model_name = model_name
        self.lock = asyncio.Lock()
        self._torch = None

    @property
    def tokenizer(self) -> Any:
        return self.fe.tokenizer

    def warmup(self, max_new_tokens: int = 32) -> None:
        """Capture decode CUDA graphs using a tiny in-memory image."""
        import torch

        if max_new_tokens <= 0:
            return
        messages = _dummy_warmup_messages()
        self.fe.set_prompt(messages)
        with torch.inference_mode():
            self.fe.prefill_graph()
            self.fe.warmup_decode_graphs(max_new_tokens)
        torch.cuda.synchronize()
        log.info("warmup: captured decode graphs for %d tokens", max_new_tokens)

    def _prefill_logits(self):
        import torch

        with torch.inference_mode():
            return self.fe.prefill_graph()

    def _decode_logits(self, token: int, cache_pos: int, rope_pos: int):
        import torch

        with torch.inference_mode():
            return self.fe._decode_step_graph(token, cache_pos, rope_pos)

    async def stream_generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        seed: int | None = None,
        stop: list[str] | None = None,
    ) -> AsyncIterator[tuple[Any, ...]]:
        """Yield ``('content', str)``, ``('tool_calls', list)``, ``('finish', reason, usage)``."""
        import torch

        async with self.lock:
            fe = self.fe
            tok = self.tokenizer

            rng = None
            if seed is not None:
                rng = torch.Generator(device=fe.device)
                rng.manual_seed(int(seed))

            enable_tools = bool(tools)
            fast_text = not enable_tools and not stop
            parser = None if fast_text else StreamParser(
                tok,
                stop_strings=stop or [],
                enable_tools=enable_tools,
            )

            t0 = time.perf_counter()
            fe.set_prompt(messages, tools=tools)
            prompt_state = fe._prompt
            if prompt_state is None:
                raise RuntimeError("set_prompt did not build prompt state")
            prompt_len = int(prompt_state["S"])
            base_slot = prompt_len
            base_rope = int(prompt_state["mrope_max"]) + 1

            logits = self._prefill_logits()
            prefill_s = time.perf_counter() - t0

            new_tokens: list[int] = []
            finish_reason = "length"
            first_token_s: float | None = None

            def _emit_token(cur_tok: int) -> tuple[str, list[dict[str, Any]], bool]:
                if fast_text:
                    delta = tok.decode([cur_tok], skip_special_tokens=False)
                    return delta, [], False
                assert parser is not None
                return parser.feed([cur_tok])

            for step in range(max_tokens):
                row = logits[0] if logits.dim() > 1 else logits
                cur_tok = sample_token(
                    row.float(),
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    rng=rng,
                )
                if first_token_s is None:
                    first_token_s = time.perf_counter() - t0
                new_tokens.append(cur_tok)

                if cur_tok in fe._eos_token_ids:
                    if parser is not None:
                        delta, tcs, _ = parser.feed([], final=True)
                        if delta:
                            yield ("content", delta)
                        if tcs:
                            yield ("tool_calls", tcs)
                    finish_reason = (
                        "tool_calls"
                        if parser is not None
                        and parser._tool_calls_emitted
                        and not parser._buffer.strip()
                        else "stop"
                    )
                    break

                delta, tcs, stop_hit = _emit_token(cur_tok)
                if delta:
                    yield ("content", delta)
                if tcs:
                    yield ("tool_calls", tcs)
                if stop_hit:
                    finish_reason = "stop"
                    break

                if step >= max_tokens - 1:
                    break

                logits = self._decode_logits(
                    cur_tok,
                    base_slot + step,
                    base_rope + step,
                )
                if step % 8 == 0:
                    await asyncio.sleep(0)
            else:
                if parser is not None:
                    delta, tcs, _ = parser.feed([], final=True)
                    if delta:
                        yield ("content", delta)
                    if tcs:
                        yield ("tool_calls", tcs)

            wall = time.perf_counter() - t0
            decode_s = max(0.0, wall - prefill_s)
            usage = {
                "prompt_tokens": prompt_len,
                "completion_tokens": len(new_tokens),
                "total_tokens": prompt_len + len(new_tokens),
                "prefill_ms": round(prefill_s * 1000, 1),
                "ttft_ms": round((first_token_s or prefill_s) * 1000, 1),
                "decode_ms": round(decode_s * 1000, 1),
                "wall_s": round(wall, 3),
                "tok_per_s": (
                    round(len(new_tokens) / decode_s, 1) if decode_s > 0 else 0
                ),
            }
            yield ("finish", finish_reason, usage)
