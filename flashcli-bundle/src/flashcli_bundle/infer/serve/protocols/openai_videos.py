"""OpenAI-style asynchronous video job host routes."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from flashcli_bundle.infer.engines.base import VideoRequest
from flashcli_bundle.infer.serve.inference import InferenceGate
from flashcli_bundle.infer.serve.protocols.common import call_engine, new_id


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return dict(job)


def _coerce_job(job: Any) -> dict[str, Any]:
    if not isinstance(job, dict):
        job = getattr(job, "__dict__", None) or {}
    payload = _job_payload(job)
    payload.setdefault("object", "video")
    payload.setdefault("status", "queued")
    payload.setdefault("created_at", int(time.time()))
    return payload


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    async def create(req: VideoRequest, request_id: str) -> Any:
        method = getattr(engine, "create_video", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose video generation", "type": "not_implemented"}},
            )
        try:
            job = await call_engine(gate, engine, request_id, method, req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"video creation failed: {exc}") from exc
        if not isinstance(job, dict):
            job = getattr(job, "__dict__", None) or {}
        if "id" not in job:
            raise HTTPException(500, "engine create_video() must return a job with id")
        job.setdefault("object", "video")
        job.setdefault("status", "queued")
        job.setdefault("created_at", int(time.time()))
        return _job_payload(job)

    @app.post("/v1/videos")
    async def videos(request: Request):
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            prompt = str(form.get("prompt", ""))
            reference = form.get("input_reference")
            payload = await reference.read() if hasattr(reference, "read") else None
            req = VideoRequest(
                prompt=prompt,
                model=str(form.get("model", "")),
                seconds=int(form["seconds"]) if form.get("seconds") else None,
                size=str(form["size"]) if form.get("size") else None,
                input_reference=payload,
                extras={str(k): str(v) for k, v in form.items() if not hasattr(v, "read") and k not in {"prompt", "model", "seconds", "size"}},
            )
        else:
            body = await request.json()
            req = VideoRequest(
                prompt=str(body.get("prompt", "")),
                model=str(body.get("model", "")),
                seconds=int(body["seconds"]) if body.get("seconds") is not None else None,
                size=str(body["size"]) if body.get("size") else None,
                extras={k: v for k, v in body.items() if k not in {"prompt", "model", "seconds", "size"} and v is not None},
            )
        return await create(req, request.headers.get("x-request-id") or new_id("video"))

    @app.get("/v1/videos")
    async def list_videos(request: Request):
        method = getattr(engine, "list_videos", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose video listing", "type": "not_implemented"}},
            )
        raw_limit = request.query_params.get("limit")
        try:
            limit = int(raw_limit) if raw_limit is not None else 20
        except ValueError:
            raise HTTPException(400, "limit must be an integer") from None
        if limit < 1 or limit > 100:
            raise HTTPException(400, "limit must be between 1 and 100")
        try:
            jobs = method()
            if hasattr(jobs, "__await__"):
                jobs = await jobs
        except Exception as exc:
            raise HTTPException(500, f"video list failed: {exc}") from exc
        if not isinstance(jobs, (list, tuple)):
            raise HTTPException(500, "engine list_videos() must return a list")
        data = [_coerce_job(job) for job in jobs]
        return {
            "object": "list",
            "data": data[:limit],
            "has_more": len(data) > limit,
        }

    @app.get("/v1/videos/{video_id}")
    async def get_video(video_id: str):
        method = getattr(engine, "get_video", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose video generation", "type": "not_implemented"}},
            )
        try:
            job = method(video_id)
            if hasattr(job, "__await__"):
                job = await job
        except KeyError:
            raise HTTPException(404, f"video {video_id!r} not found") from None
        except Exception as exc:
            raise HTTPException(500, f"video lookup failed: {exc}") from exc
        if job is None:
            raise HTTPException(404, f"video {video_id!r} not found")
        if not isinstance(job, dict):
            job = getattr(job, "__dict__", None) or {}
        job.setdefault("object", "video")
        return _job_payload(job)

    @app.get("/v1/videos/{video_id}/content")
    async def video_content(video_id: str):
        method = getattr(engine, "download_video", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose video generation", "type": "not_implemented"}},
            )
        try:
            payload = method(video_id)
            if hasattr(payload, "__await__"):
                payload = await payload
        except KeyError:
            raise HTTPException(404, f"video {video_id!r} not found") from None
        except Exception as exc:
            raise HTTPException(500, f"video download failed: {exc}") from exc
        return Response(content=payload, media_type="video/mp4")

    @app.delete("/v1/videos/{video_id}")
    async def delete_video(video_id: str):
        method = getattr(engine, "delete_video", None)
        if method is None:
            return JSONResponse(
                status_code=501,
                content={"error": {"message": "the bundle does not expose video generation", "type": "not_implemented"}},
            )
        try:
            deleted = method(video_id)
            if hasattr(deleted, "__await__"):
                deleted = await deleted
        except KeyError:
            raise HTTPException(404, f"video {video_id!r} not found") from None
        return {"id": video_id, "object": "video.deleted", "deleted": bool(deleted)}
