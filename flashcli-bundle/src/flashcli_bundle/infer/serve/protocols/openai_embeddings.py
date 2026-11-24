"""OpenAI /v1/embeddings host route."""

from __future__ import annotations

import base64
import struct
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from flashcli_bundle.infer.engines.base import EmbeddingRequest, EmbeddingResult
from flashcli_bundle.infer.serve.inference import InferenceGate
from flashcli_bundle.infer.serve.protocols.common import call_engine, new_id


def _parse(body: dict[str, Any]) -> EmbeddingRequest:
    raw = body.get("input")
    if isinstance(raw, str):
        inputs: list[str] | list[list[int]] = [raw]
    elif isinstance(raw, list):
        if all(isinstance(item, str) for item in raw):
            inputs = list(raw)
        elif all(isinstance(item, int) for item in raw):
            inputs = [list(raw)]
        elif all(
            isinstance(item, list) and all(isinstance(t, int) for t in item)
            for item in raw
        ):
            inputs = [list(item) for item in raw]
        else:
            raise HTTPException(400, "input must be a string, string array, or token array")
    else:
        raise HTTPException(400, "input is required")
    if not inputs:
        raise HTTPException(400, "input must not be empty")
    dimensions = body.get("dimensions")
    if dimensions is not None:
        try:
            dimensions = int(dimensions)
        except (TypeError, ValueError):
            raise HTTPException(400, "dimensions must be an integer") from None
        if dimensions <= 0:
            raise HTTPException(400, "dimensions must be > 0")
    encoding = str(body.get("encoding_format", "float") or "float")
    if encoding not in ("float", "base64"):
        raise HTTPException(400, "encoding_format must be 'float' or 'base64'")
    extras = {
        k: v
        for k, v in body.items()
        if k not in {"input", "model", "dimensions", "encoding_format", "user"}
        and v is not None
    }
    return EmbeddingRequest(
        input=inputs,
        model=str(body.get("model", "")),
        dimensions=dimensions,
        encoding_format=encoding,
        extras=extras,
    )


def _encode(values: list[float], encoding: str) -> Any:
    if encoding == "base64":
        return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()
    return values


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.post("/v1/embeddings")
    async def embeddings(request: Request, body: dict[str, Any]):
        req = _parse(body)
        method = getattr(engine, "embed", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={
                    "error": {
                        "message": "the bundle does not expose embeddings",
                        "type": "not_implemented",
                        "code": "embeddings_not_implemented",
                    }
                },
            )
        request_id = request.headers.get("x-request-id") or new_id("embd")
        try:
            result = await call_engine(gate, engine, request_id, method, req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"embedding failed: {exc}") from exc
        if not isinstance(result, EmbeddingResult):
            raise HTTPException(500, "engine embed() must return EmbeddingResult")
        if len(result.embeddings) != len(req.input):
            raise HTTPException(500, "engine returned a different number of embeddings")
        usage = result.usage or {}
        prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "embedding": _encode(list(values), req.encoding_format),
                    "index": index,
                }
                for index, values in enumerate(result.embeddings)
            ],
            "model": req.model or engine.model_id,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "total_tokens": int(usage.get("total_tokens", prompt_tokens) or 0),
            },
        }
