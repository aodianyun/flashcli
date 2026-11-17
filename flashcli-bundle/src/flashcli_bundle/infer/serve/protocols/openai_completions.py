"""OpenAI legacy /v1/completions route (host-owned capability openai.completions)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from flashcli_bundle.infer.engines.base import ChatMessage, ChatRequest
from flashcli_bundle.infer.serve.inference import InferenceGate
from flashcli_bundle.infer.serve.protocols.common import (
    chat_chunks,
    chat_once,
    gpu_busy,
    new_id,
    now,
    sse,
)

_UNSUPPORTED = ("logprobs", "best_of", "suffix")


def _parse(body: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    prompt = body.get("prompt")
    if isinstance(prompt, str):
        prompts = [prompt]
    elif isinstance(prompt, list) and all(isinstance(p, str) for p in prompt):
        prompts = list(prompt)
    else:
        raise HTTPException(400, "prompt must be a string or array of strings")
    if not prompts or any(prompt == "" for prompt in prompts):
        raise HTTPException(400, "prompt must not be empty")
    for key in _UNSUPPORTED:
        if body.get(key) is not None:
            raise HTTPException(400, f"{key} is not supported by this bundle")
    raw_n = body.get("n")
    try:
        n = int(raw_n) if raw_n is not None else 1
    except (TypeError, ValueError):
        raise HTTPException(400, "n must be an integer") from None
    if n < 1:
        raise HTTPException(400, "n must be >= 1")
    if n > 1 and not body.get("stream"):
        raise HTTPException(501, "n>1 is not implemented yet")
    if n > 1:
        raise HTTPException(501, "streaming n>1 is not implemented yet")
    return prompts, body


def _request(prompt: str, body: dict[str, Any]) -> ChatRequest:
    stop = body.get("stop")
    if isinstance(stop, str):
        stop = [stop]
    return ChatRequest(
        messages=[ChatMessage(role="user", content=prompt)],
        max_tokens=int(body.get("max_tokens", 16) or 16),
        temperature=float(body.get("temperature", 0.0) or 0.0),
        top_p=float(body.get("top_p", 1.0) or 1.0),
        stream=bool(body.get("stream")),
        stop=stop if isinstance(stop, list) else None,
        seed=body.get("seed"),
        extras={
            k: v
            for k, v in body.items()
            if k
            not in {
                "prompt", "model", "max_tokens", "temperature", "top_p",
                "stream", "stop", "seed", "n", "echo", "user",
            }
            and v is not None
        },
    )


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.post("/v1/completions")
    async def completions(request: Request, body: dict[str, Any]):
        prompts, parsed = _parse(body)
        model = str(body.get("model") or engine.model_id)
        completion_id = new_id("cmpl")
        created = now()

        if not parsed.get("stream"):
            choices = []
            usage: dict[str, Any] = {}
            for index, prompt in enumerate(prompts):
                try:
                    result = await chat_once(gate, engine, request.headers.get("x-request-id", completion_id), _request(prompt, body))
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(500, f"inference failed: {exc}") from exc
                text = result.content or ""
                if body.get("echo"):
                    text = prompt + text
                choices.append({
                    "text": text,
                    "index": index,
                    "logprobs": None,
                    "finish_reason": result.finish_reason,
                })
                usage = result.usage or usage
            return {
                "id": completion_id,
                "object": "text_completion",
                "created": created,
                "model": model,
                "choices": choices,
                "usage": usage,
            }

        prompt = prompts[0]
        req = _request(prompt, body)

        async def stream():
            yield sse({
                "id": completion_id,
                "object": "text_completion",
                "created": created,
                "model": model,
                "choices": [{"text": "", "index": 0, "logprobs": None, "finish_reason": None}],
            })
            try:
                await gate.acquire(request.headers.get("x-request-id", completion_id))
            except Exception:
                raise gpu_busy(engine.model_id) from None
            try:
                async for chunk in chat_chunks(engine, req):
                    if chunk.content_delta:
                        yield sse({
                            "id": completion_id,
                            "object": "text_completion",
                            "created": created,
                            "model": model,
                            "choices": [{
                                "text": chunk.content_delta,
                                "index": 0,
                                "logprobs": None,
                                "finish_reason": None,
                            }],
                        })
                    if chunk.finish_reason:
                        yield sse({
                            "id": completion_id,
                            "object": "text_completion",
                            "created": created,
                            "model": model,
                            "choices": [{
                                "text": "",
                                "index": 0,
                                "logprobs": None,
                                "finish_reason": chunk.finish_reason,
                            }],
                        })
                yield "data: [DONE]\n\n"
            finally:
                gate.release()

        return StreamingResponse(stream(), media_type="text/event-stream")
