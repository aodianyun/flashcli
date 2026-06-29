"""Message conversion for Qwen3-VL bundle (OpenAI <-> frontend format)."""

from __future__ import annotations

import base64
import io
import urllib.request
from pathlib import Path
from typing import Any

from flashcli_bundle.protocol import ChatMessage, ChatRequest


def _load_image(url_or_path: str):
    from PIL import Image

    if url_or_path.startswith("data:"):
        raw = base64.b64decode(url_or_path.split(",", 1)[1])
    elif url_or_path.startswith(("http://", "https://")):
        with urllib.request.urlopen(url_or_path) as resp:
            raw = resp.read()
    else:
        with open(url_or_path, "rb") as fh:
            raw = fh.read()
    return Image.open(io.BytesIO(raw)).convert("RGB")


def run_messages_from_prompt_image(prompt: str, image_path: str) -> list[dict[str, Any]]:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    from PIL import Image

    image = Image.open(path).convert("RGB")
    return [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt or "Describe this image."},
            ],
        }
    ]


def run_messages_from_prompt(
    prompt: str,
    *,
    image_path: str | None = None,
) -> list[dict[str, Any]]:
    if image_path:
        return run_messages_from_prompt_image(prompt, image_path)
    return [{"role": "user", "content": prompt or ""}]


def messages_from_request(req: ChatRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in req.messages:
        msg: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        out.append(msg)
    return out


def _convert_content_part(part: dict[str, Any]) -> dict[str, Any]:
    ptype = part.get("type")
    if ptype == "text":
        return {"type": "text", "text": part.get("text", "")}
    if ptype == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        return {"type": "image", "image": _load_image(url)}
    if ptype == "image":
        return part
    raise ValueError(f"unsupported message content part type: {ptype!r}")


def openai_messages_to_frontend(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, str) or content is None:
            entry: dict[str, Any] = {"role": role, "content": content or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            out.append(entry)
            continue
        if not isinstance(content, list):
            raise ValueError("message.content must be string or list")
        parts = [_convert_content_part(p) for p in content if isinstance(p, dict)]
        out.append({"role": role, "content": parts})
    return out
