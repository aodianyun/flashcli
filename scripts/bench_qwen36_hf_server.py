#!/usr/bin/env python3
"""OpenAI-compatible HTTP server — conventional PyTorch / HuggingFace baseline (no FlashRT).

Uses ``transformers.AutoModelForCausalLM.generate`` with greedy decoding
(``do_sample=False``). Intended as the non-FlashRT comparison arm for
``scripts/bench_qwen36_compare.sh``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Iterator

log = logging.getLogger("qwen36_hf_server")

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _sse(obj: Any) -> str:
    return f"data: {_json_dumps(obj)}\n\n"


def _parse_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages is required (non-empty list)")
    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("each message must be an object")
        if msg.get("role") not in ("system", "user", "assistant", "tool"):
            raise ValueError(f"unsupported role: {msg.get('role')!r}")
    return messages


def _max_tokens(body: dict[str, Any]) -> int:
    raw = body.get("max_tokens", body.get("max_completion_tokens", 256))
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_tokens must be an integer") from exc
    if n < 1:
        raise ValueError("max_tokens must be >= 1")
    return n


class HfQwen36Engine:
    """Single-GPU greedy chat engine via HuggingFace transformers."""

    def __init__(
        self,
        *,
        checkpoint: str,
        device: str,
        model_name: str,
        max_seq: int,
        max_output_tokens: int,
        attn_implementation: str,
        torch_dtype: str,
    ) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = torch.device(device)
        self.model_name = model_name
        self.max_seq = int(max_seq)
        self.max_output_tokens = int(max_output_tokens)
        self._lock = asyncio.Lock()

        dtype_map = {
            "auto": "auto",
            "bf16": torch.bfloat16,
            "bfloat16": torch.bfloat16,
            "fp16": torch.float16,
            "float16": torch.float16,
        }
        dtype = dtype_map.get(torch_dtype.lower(), "auto")

        log.info(
            "Loading HF model %s (attn=%s, dtype=%s, max_seq=%d) …",
            checkpoint,
            attn_implementation,
            torch_dtype,
            self.max_seq,
        )
        t0 = time.perf_counter()
        load_kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "device_map": {"": str(self.device)},
            "low_cpu_mem_usage": True,
            "trust_remote_code": True,
        }
        if attn_implementation and attn_implementation not in ("default", "auto"):
            load_kwargs["attn_implementation"] = attn_implementation
        try:
            self.model = AutoModelForCausalLM.from_pretrained(checkpoint, **load_kwargs)
        except ImportError as exc:
            raise SystemExit(
                f"Failed to import deps for {checkpoint!r}: {exc}\n"
                "NVFP4 checkpoints often need: pip install compressed-tensors"
            ) from exc
        except Exception as exc:
            msg = str(exc)
            hint = ""
            if "compressed" in msg.lower() or "nvfp4" in msg.lower() or "quant" in msg.lower():
                hint = "\nTry: pip install compressed-tensors transformers -U"
            raise SystemExit(
                f"Failed to load checkpoint {checkpoint!r} with transformers: {exc}{hint}"
            ) from exc
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        log.info("HF model ready in %.1f s", time.perf_counter() - t0)

    def tokenize_chat(self, messages: list[dict[str, Any]]) -> list[int]:
        kwargs: dict[str, Any] = {
            "tokenize": False,
            "add_generation_prompt": True,
        }
        try:
            text = self.tokenizer.apply_chat_template(
                messages,
                enable_thinking=False,
                **kwargs,
            )
        except TypeError:
            text = self.tokenizer.apply_chat_template(messages, **kwargs)
        ids = self.tokenizer(text, return_tensors="pt").input_ids[0].tolist()
        return [int(x) for x in ids]

    def _generate_greedy(
        self,
        prompt_ids: list[int],
        *,
        max_new_tokens: int,
    ) -> tuple[list[int], dict[str, Any]]:
        import torch

        if len(prompt_ids) + int(max_new_tokens) > self.max_seq:
            raise ValueError(
                f"prompt + max_tokens = {len(prompt_ids) + int(max_new_tokens)} "
                f"exceeds max_seq {self.max_seq}"
            )

        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=self.device)
        eos_id = self.model.config.eos_token_id
        if isinstance(eos_id, (list, tuple)):
            eos_set = {int(x) for x in eos_id}
        elif eos_id is not None:
            eos_set = {int(eos_id)}
        else:
            eos_set = set()

        generated: list[int] = []
        past_key_values = None
        cur = input_ids

        torch.cuda.synchronize(self.device)
        t_prefill0 = time.perf_counter()
        with torch.no_grad():
            out = self.model(input_ids=cur, use_cache=True, return_dict=True)
        torch.cuda.synchronize(self.device)
        t_prefill1 = time.perf_counter()
        past_key_values = out.past_key_values
        logits = out.logits[:, -1, :]
        next_id = int(logits.argmax(dim=-1).item())
        prefill_ms = (t_prefill1 - t_prefill0) * 1000.0
        ttft_ms = prefill_ms

        if next_id not in eos_set and len(generated) < int(max_new_tokens):
            generated.append(next_id)

        torch.cuda.synchronize(self.device)
        t_decode0 = time.perf_counter()
        steps = 0
        while len(generated) < int(max_new_tokens):
            cur = torch.tensor([[generated[-1]]], dtype=torch.long, device=self.device)
            with torch.no_grad():
                out = self.model(
                    input_ids=cur,
                    past_key_values=past_key_values,
                    use_cache=True,
                    return_dict=True,
                )
            past_key_values = out.past_key_values
            next_id = int(out.logits[:, -1, :].argmax(dim=-1).item())
            steps += 1
            if next_id in eos_set:
                break
            generated.append(next_id)
        torch.cuda.synchronize(self.device)
        t_decode1 = time.perf_counter()

        decode_ms = max(0.0, (t_decode1 - t_decode0) * 1000.0)
        completion_tokens = len(generated)
        decode_tok_per_s = (
            completion_tokens * 1000.0 / decode_ms if decode_ms > 0 and completion_tokens else 0.0
        )
        usage = {
            "prompt_tokens": len(prompt_ids),
            "completion_tokens": completion_tokens,
            "total_tokens": len(prompt_ids) + completion_tokens,
            "prefill_ms": prefill_ms,
            "ttft_ms": ttft_ms,
            "decode_ms": decode_ms,
            "decode_tok_per_s": decode_tok_per_s,
            "tok_per_s": decode_tok_per_s,
            "route": "hf_transformers",
        }
        return generated, usage

    def stream_openai(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int,
        model: str,
    ) -> Iterator[str]:
        import torch

        prompt_ids = self.tokenize_chat(messages)
        max_new = min(int(max_tokens), self.max_output_tokens)
        if len(prompt_ids) + max_new > self.max_seq:
            raise ValueError(
                f"prompt + max_tokens = {len(prompt_ids) + max_new} "
                f"exceeds max_seq {self.max_seq}"
            )

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        yield _sse(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
        )

        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=self.device)
        eos_id = self.model.config.eos_token_id
        if isinstance(eos_id, (list, tuple)):
            eos_set = {int(x) for x in eos_id}
        elif eos_id is not None:
            eos_set = {int(eos_id)}
        else:
            eos_set = set()

        generated: list[int] = []
        past_key_values = None

        torch.cuda.synchronize(self.device)
        t_prefill0 = time.perf_counter()
        with torch.no_grad():
            out = self.model(input_ids=input_ids, use_cache=True, return_dict=True)
        torch.cuda.synchronize(self.device)
        t_prefill1 = time.perf_counter()
        past_key_values = out.past_key_values
        next_id = int(out.logits[:, -1, :].argmax(dim=-1).item())
        prefill_ms = (t_prefill1 - t_prefill0) * 1000.0

        def emit_token(tok: int) -> str:
            text = self.tokenizer.decode([tok], skip_special_tokens=False)
            return _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
            )

        torch.cuda.synchronize(self.device)
        t_decode0 = time.perf_counter()
        if next_id not in eos_set and len(generated) < max_new:
            generated.append(next_id)
            yield emit_token(next_id)

        while len(generated) < max_new:
            cur = torch.tensor([[generated[-1]]], dtype=torch.long, device=self.device)
            with torch.no_grad():
                out = self.model(
                    input_ids=cur,
                    past_key_values=past_key_values,
                    use_cache=True,
                    return_dict=True,
                )
            past_key_values = out.past_key_values
            next_id = int(out.logits[:, -1, :].argmax(dim=-1).item())
            if next_id in eos_set:
                break
            generated.append(next_id)
            yield emit_token(next_id)
        torch.cuda.synchronize(self.device)
        t_decode1 = time.perf_counter()

        decode_ms = max(0.0, (t_decode1 - t_decode0) * 1000.0)
        completion_tokens = len(generated)
        decode_tok_per_s = (
            completion_tokens * 1000.0 / decode_ms if decode_ms > 0 and completion_tokens else 0.0
        )
        usage = {
            "prompt_tokens": len(prompt_ids),
            "completion_tokens": completion_tokens,
            "total_tokens": len(prompt_ids) + completion_tokens,
            "prefill_ms": prefill_ms,
            "ttft_ms": prefill_ms,
            "decode_ms": decode_ms,
            "decode_tok_per_s": decode_tok_per_s,
            "tok_per_s": decode_tok_per_s,
            "route": "hf_transformers",
        }
        yield _sse(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage,
            }
        )
        yield "data: [DONE]\n\n"
        log.info(
            "stream done prompt=%d completion=%d prefill_ms=%.1f decode_ms=%.1f decode_tok_per_s=%.1f",
            len(prompt_ids),
            completion_tokens,
            prefill_ms,
            decode_ms,
            decode_tok_per_s,
        )


def build_app(engine: HfQwen36Engine):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import StreamingResponse

    app = FastAPI(title="Qwen3.6 PyTorch HF baseline")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "backend": "pytorch_hf",
            "model": engine.model_name,
            "max_seq": engine.max_seq,
            "speculative": False,
        }

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": engine.model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "pytorch-hf",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(raw: dict[str, Any]):
        try:
            messages = _parse_messages(raw)
            max_tokens = _max_tokens(raw)
            stream = bool(raw.get("stream", False))
            if max_tokens > engine.max_output_tokens:
                raise ValueError(
                    f"max_tokens must be <= {engine.max_output_tokens}"
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        async with engine._lock:
            if stream:
                def _gen():
                    yield from engine.stream_openai(
                        messages=messages,
                        max_tokens=max_tokens,
                        model=engine.model_name,
                    )

                return StreamingResponse(
                    _gen(),
                    media_type="text/event-stream",
                    headers=SSE_HEADERS,
                )

            try:
                prompt_ids = engine.tokenize_chat(messages)
                generated, usage = await asyncio.to_thread(
                    engine._generate_greedy,
                    prompt_ids,
                    max_new_tokens=max_tokens,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

            text = engine.tokenizer.decode(generated, skip_special_tokens=False)
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": engine.model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True, help="HF model directory or repo id")
    p.add_argument("--model-name", default="qwen3.6-27b-fp8")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--max-seq", type=int, default=32768)
    p.add_argument("--max-output-tokens", type=int, default=16384)
    p.add_argument(
        "--attn",
        default="sdpa",
        help="transformers attn_implementation (default sdpa = conventional PyTorch path)",
    )
    p.add_argument(
        "--dtype",
        default="auto",
        help="torch dtype: auto, bf16, fp16",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default="info")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    engine = HfQwen36Engine(
        checkpoint=args.checkpoint,
        device=args.device,
        model_name=args.model_name,
        max_seq=args.max_seq,
        max_output_tokens=args.max_output_tokens,
        attn_implementation=args.attn,
        torch_dtype=args.dtype,
    )
    app = build_app(engine)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
