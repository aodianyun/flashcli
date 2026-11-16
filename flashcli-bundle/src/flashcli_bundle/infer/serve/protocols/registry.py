"""Capability-to-route registry for host-owned protocol endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from flashcli_bundle.capabilities import (
    OPENAI_AUDIO_SPEECH,
    OPENAI_AUDIO_TRANSCRIPTIONS,
    OPENAI_AUDIO_TRANSLATIONS,
    OPENAI_CHAT,
    OPENAI_COMPLETIONS,
    OPENAI_EMBEDDINGS,
    OPENAI_IMAGES_EDITS,
    OPENAI_IMAGES_GENERATIONS,
    OPENAI_IMAGES_VARIATIONS,
    OPENAI_MODERATIONS,
    OPENAI_RESPONSES,
    OPENAI_VIDEOS,
)

# Capabilities implemented by host-owned modules.
IMPLEMENTED = frozenset(
    {
        OPENAI_CHAT,
        OPENAI_COMPLETIONS,
        OPENAI_RESPONSES,
        OPENAI_EMBEDDINGS,
        OPENAI_AUDIO_TRANSCRIPTIONS,
        OPENAI_AUDIO_TRANSLATIONS,
        OPENAI_AUDIO_SPEECH,
        OPENAI_IMAGES_GENERATIONS,
        OPENAI_IMAGES_EDITS,
        OPENAI_IMAGES_VARIATIONS,
        OPENAI_MODERATIONS,
        OPENAI_VIDEOS,
        "anthropic.messages",
        "anthropic.count_tokens",
        "anthropic.models",
    }
)

# Planned HTTP endpoints that return an explicit 501 until implemented.
# Realtime is WebSocket-only and needs a dedicated mount later.
PLANNED_HTTP: dict[str, tuple[str, str]] = {}


def mount_unimplemented(app: FastAPI, capabilities: set[str]) -> None:
    for capability, (method, path) in PLANNED_HTTP.items():
        if capability not in capabilities or capability in IMPLEMENTED:
            continue

        async def not_implemented(_capability: str = capability) -> Any:
            return JSONResponse(
                status_code=501,
                content={
                    "error": {
                        "message": f"capability {_capability!r} is declared but not implemented by this host yet",
                        "type": "not_implemented",
                        "code": "capability_not_implemented",
                    }
                },
            )

        app.add_api_route(path, not_implemented, methods=[method])
