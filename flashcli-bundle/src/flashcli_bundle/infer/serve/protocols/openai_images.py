"""OpenAI image generation/edit/variation host routes."""

from __future__ import annotations

import base64
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from flashcli_bundle.infer.engines.base import ImageGenerationRequest, ImageGenerationResult


def _str(form: Any, key: str, default: str | None = None) -> str | None:
    value = form.get(key)
    if value is None or value == "":
        return default
    return str(value)


def _int(form: Any, key: str, default: int) -> int:
    value = _str(form, key)
    return int(value) if value is not None else default


async def _files(form: Any, key: str) -> list[bytes]:
    values = form.getlist(key) or form.getlist(f"{key}[]")
    out: list[bytes] = []
    for value in values:
        if hasattr(value, "read"):
            out.append(await value.read())
    return out


def _data(request: ImageGenerationRequest, result: ImageGenerationResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for image in result.images:
        item: dict[str, Any] = {}
        if isinstance(image, bytes):
            if request.response_format == "b64_json" or result.response_format == "b64_json":
                item["b64_json"] = base64.b64encode(image).decode()
            else:
                item["url"] = "data:image/png;base64," + base64.b64encode(image).decode()
        else:
            item["b64_json" if request.response_format == "b64_json" else "url"] = image
        if result.revised_prompt:
            item["revised_prompt"] = result.revised_prompt
        out.append(item)
    return out


def _response(request: ImageGenerationRequest, result: ImageGenerationResult) -> dict[str, Any]:
    return {
        "created": int(time.time()),
        "data": _data(request, result),
        "usage": result.usage,
    }


def mount(app: FastAPI, engine: Any) -> None:
    method = getattr(engine, "generate_images", None)

    def unavailable() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={"error": {"message": "the bundle does not expose images", "type": "not_implemented"}},
        )

    async def call(req: ImageGenerationRequest) -> Any:
        if method is None:
            return unavailable()
        try:
            result = method(req)
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:
            raise HTTPException(500, f"image generation failed: {exc}") from exc
        if not isinstance(result, ImageGenerationResult):
            raise HTTPException(500, "engine generate_images() must return ImageGenerationResult")
        return _response(req, result)

    @app.post("/v1/images/generations")
    async def generations(body: dict[str, Any]):
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise HTTPException(400, "prompt is required")
        return await call(
            ImageGenerationRequest(
                prompt=prompt,
                model=str(body.get("model", "")),
                mode="generate",
                n=int(body.get("n", 1) or 1),
                size=str(body.get("size", "1024x1024")),
                quality=str(body.get("quality", "auto")),
                style=body.get("style"),
                response_format=str(body.get("response_format", "url") or "url"),
                extras={k: v for k, v in body.items() if k not in {
                    "prompt", "model", "n", "size", "quality", "style", "response_format"
                }},
            )
        )

    async def form_request(request: Request, mode: str) -> ImageGenerationRequest:
        form = await request.form()
        prompt = _str(form, "prompt", "") or ""
        if mode == "edit" and not prompt:
            raise HTTPException(400, "prompt is required")
        images = await _files(form, "image")
        if not images:
            raise HTTPException(400, "image is required")
        masks = await _files(form, "mask")
        return ImageGenerationRequest(
            prompt=prompt,
            model=_str(form, "model", "") or "",
            mode=mode,
            n=_int(form, "n", 1),
            size=_str(form, "size", "1024x1024") or "1024x1024",
            quality=_str(form, "quality", "auto") or "auto",
            style=_str(form, "style"),
            response_format=_str(form, "response_format", "url") or "url",
            images=images,
            mask=masks[0] if masks else None,
            extras={str(k): str(v) for k, v in form.items() if not hasattr(v, "read") and k not in {
                "prompt", "model", "n", "size", "quality", "style", "response_format"
            }},
        )

    @app.post("/v1/images/edits")
    async def edits(request: Request):
        return await call(await form_request(request, "edit"))

    @app.post("/v1/images/variations")
    async def variations(request: Request):
        return await call(await form_request(request, "variation"))
