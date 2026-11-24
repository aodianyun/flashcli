"""OpenAI /v1/moderations host route."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from flashcli_bundle.infer.engines.base import ModerationRequest, ModerationResult
from flashcli_bundle.infer.serve.inference import InferenceGate
from flashcli_bundle.infer.serve.protocols.common import call_engine, new_id


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.post("/v1/moderations")
    async def moderations(request: Request, body: dict[str, Any]):
        raw = body.get("input")
        if isinstance(raw, str):
            inputs = [raw]
        elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            inputs = list(raw)
        else:
            raise HTTPException(400, "input must be a string or array of strings")
        if not inputs:
            raise HTTPException(400, "input must not be empty")
        method = getattr(engine, "moderate", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose moderation", "type": "not_implemented"}},
            )
        req = ModerationRequest(
            input=inputs,
            model=str(body.get("model", "")),
            extras={k: v for k, v in body.items() if k not in {"input", "model"} and v is not None},
        )
        try:
            result = await call_engine(
                gate,
                engine,
                request.headers.get("x-request-id") or new_id("modr"),
                method,
                req,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"moderation failed: {exc}") from exc
        if not isinstance(result, ModerationResult):
            raise HTTPException(500, "engine moderate() must return ModerationResult")
        if len(result.results) != len(inputs):
            raise HTTPException(500, "engine returned a different number of moderation results")
        return {
            "id": new_id("modr"),
            "model": req.model or engine.model_id,
            "results": result.results,
            "usage": result.usage,
        }
