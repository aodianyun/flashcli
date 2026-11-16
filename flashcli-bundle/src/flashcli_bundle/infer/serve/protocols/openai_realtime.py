"""OpenAI Realtime WebSocket transport hook (host-owned route)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def mount(app: FastAPI, engine: Any) -> None:
    @app.websocket("/v1/realtime")
    async def realtime(websocket: WebSocket):
        await websocket.accept()
        model = websocket.query_params.get("model") or engine.model_id
        handler = getattr(engine, "realtime_session", None)
        if handler is None:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "error": {
                            "type": "not_implemented",
                            "message": "the bundle does not expose realtime_session",
                        },
                    }
                )
            )
            await websocket.close(code=1011)
            return
        try:
            result = handler(websocket, model)
            if hasattr(result, "__await__"):
                await result
        except WebSocketDisconnect:
            return
        except Exception as exc:
            try:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "error": {"type": "api_error", "message": str(exc)},
                        }
                    )
                )
            except Exception:
                pass
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
