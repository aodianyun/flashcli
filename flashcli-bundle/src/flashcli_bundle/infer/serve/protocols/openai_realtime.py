"""OpenAI Realtime WebSocket transport and host-owned session state machine.

When the bundle implements ``realtime_session(websocket, model)`` the host
delegates the whole event protocol to it (bundle-owned). Otherwise the host
runs a text-focused state machine on top of ``chat``/``chat_stream``:
session updates, conversation items, input audio buffering (optional
transcription through ``transcribe``), and response create/cancel.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from flashcli_bundle.infer.engines.base import (
    AudioTranscriptionRequest,
    ChatMessage,
    ChatRequest,
)
from flashcli_bundle.infer.serve.inference import GpuBusyError, InferenceGate
from flashcli_bundle.infer.serve.protocols.common import chat_chunks, new_id

_DEFAULT_SESSION: dict[str, Any] = {
    "modalities": ["text"],
    "instructions": "",
    "voice": "alloy",
    "input_audio_format": "pcm16",
    "output_audio_format": "pcm16",
    "input_audio_transcription": None,
    "turn_detection": None,
    "tools": [],
    "tool_choice": "auto",
    "temperature": 0.8,
    "max_response_output_tokens": "inf",
}


def _tool_payload(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict) or str(tool.get("type", "function")) != "function":
        return None
    name = str(tool.get("name", ""))
    if not name:
        return None
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": str(tool.get("description", "")),
            "parameters": tool.get("parameters", {"type": "object"}),
        },
    }


def _message_from_item(item: dict[str, Any]) -> ChatMessage | None:
    role = str(item.get("role", "user"))
    parts: list[dict[str, Any]] = []
    texts: list[str] = []
    content = item.get("content")
    if isinstance(content, str):
        return ChatMessage(role=role, content=content)
    if not isinstance(content, list):
        return ChatMessage(role=role, content="")
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type", "text"))
        if kind in ("input_text", "output_text", "text"):
            value = str(part.get("text", ""))
            texts.append(value)
            parts.append({"type": "text", "text": value})
        elif kind in ("input_audio", "audio"):
            transcript = part.get("transcript")
            if isinstance(transcript, str) and transcript:
                texts.append(transcript)
                parts.append({"type": "text", "text": transcript})
        elif kind == "input_image":
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if url:
                parts.append({"type": "image_url", "image_url": {"url": str(url)}})
    if any(part["type"] == "image_url" for part in parts):
        return ChatMessage(role=role, content=parts)
    return ChatMessage(role=role, content="".join(texts))


def _messages(
    items: list[dict[str, Any]],
    instructions: str,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    if instructions:
        messages.append(ChatMessage(role="system", content=instructions))
    for item in items:
        kind = str(item.get("type", "message"))
        if kind == "message":
            message = _message_from_item(item)
            if message is not None:
                messages.append(message)
        elif kind == "function_call":
            messages.append(
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[{
                        "id": str(item.get("call_id") or item.get("id") or new_id("call")),
                        "type": "function",
                        "function": {
                            "name": str(item.get("name", "")),
                            "arguments": item.get("arguments") or "{}",
                        },
                    }],
                )
            )
        elif kind == "function_call_output":
            messages.append(
                ChatMessage(
                    role="tool",
                    content=str(item.get("output", "")),
                    tool_call_id=str(item.get("call_id", "")),
                )
            )
    return messages


class _RealtimeSession:
    def __init__(self, websocket: WebSocket, engine: Any, gate: InferenceGate, model: str) -> None:
        self.websocket = websocket
        self.engine = engine
        self.gate = gate
        self.model = model
        self.session: dict[str, Any] = {
            "id": new_id("sess"),
            "object": "realtime.session",
            "model": model,
            **_DEFAULT_SESSION,
        }
        self.items: list[dict[str, Any]] = []
        self.audio = bytearray()
        self.response_task: asyncio.Task[Any] | None = None
        self.response: dict[str, Any] | None = None
        self._send_lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                await self.websocket.send_json(payload)
            except Exception:
                pass

    async def error(self, message: str, *, error_type: str = "invalid_request_error") -> None:
        await self.send(
            {
                "type": "error",
                "error": {"type": error_type, "message": message},
            }
        )

    async def run(self) -> None:
        await self.websocket.accept()
        await self.send({"type": "session.created", "session": self.session})
        try:
            while True:
                try:
                    event = await self.websocket.receive_json()
                except WebSocketDisconnect:
                    return
                except Exception:
                    await self.error("invalid JSON event")
                    continue
                if not isinstance(event, dict):
                    await self.error("event must be an object")
                    continue
                await self.handle(event)
        finally:
            if self.response_task is not None and not self.response_task.done():
                self.response_task.cancel()

    async def handle(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type", ""))
        if kind == "session.update":
            update = event.get("session")
            if isinstance(update, dict):
                for key, value in update.items():
                    if key in self.session and key not in ("id", "object", "model"):
                        self.session[key] = value
            await self.send({"type": "session.updated", "session": self.session})
        elif kind == "conversation.item.create":
            item = event.get("item")
            if not isinstance(item, dict):
                await self.error("conversation.item.create requires item")
                return
            item = dict(item)
            item.setdefault("id", new_id("item"))
            previous = self.items[-1]["id"] if self.items else None
            self.items.append(item)
            await self.send(
                {
                    "type": "conversation.item.created",
                    "previous_item_id": previous,
                    "item": item,
                }
            )
        elif kind == "conversation.item.delete":
            item_id = str(event.get("item_id", ""))
            before = len(self.items)
            self.items = [item for item in self.items if item.get("id") != item_id]
            if len(self.items) == before:
                await self.error(f"item {item_id!r} not found")
                return
            await self.send({"type": "conversation.item.deleted", "item_id": item_id})
        elif kind == "conversation.item.truncate":
            await self.send(
                {
                    "type": "conversation.item.truncated",
                    "item_id": str(event.get("item_id", "")),
                    "content_index": int(event.get("content_index", 0) or 0),
                    "audio_end_ms": int(event.get("audio_end_ms", 0) or 0),
                }
            )
        elif kind == "input_audio_buffer.append":
            data = event.get("audio")
            if not isinstance(data, str) or not data:
                await self.error("input_audio_buffer.append requires audio")
                return
            try:
                self.audio.extend(base64.b64decode(data))
            except Exception:
                await self.error("audio must be base64")
        elif kind == "input_audio_buffer.clear":
            self.audio.clear()
            await self.send({"type": "input_audio_buffer.cleared"})
        elif kind == "input_audio_buffer.commit":
            if not self.audio:
                await self.error("input audio buffer is empty")
                return
            audio = bytes(self.audio)
            self.audio.clear()
            transcript = await self._transcribe(audio)
            content: list[dict[str, Any]] = [
                {"type": "input_audio", "audio": base64.b64encode(audio).decode()}
            ]
            if transcript:
                content[0]["transcript"] = transcript
            item = {
                "id": new_id("item"),
                "type": "message",
                "role": "user",
                "content": content,
            }
            previous = self.items[-1]["id"] if self.items else None
            self.items.append(item)
            await self.send(
                {
                    "type": "input_audio_buffer.committed",
                    "previous_item_id": previous,
                    "item_id": item["id"],
                }
            )
            await self.send(
                {
                    "type": "conversation.item.created",
                    "previous_item_id": previous,
                    "item": item,
                }
            )
        elif kind == "response.create":
            if self.response_task is not None and not self.response_task.done():
                await self.error("a response is already in progress")
                return
            overrides = event.get("response")
            self.response_task = asyncio.create_task(
                self._respond(overrides if isinstance(overrides, dict) else {})
            )
        elif kind == "response.cancel":
            if self.response_task is None or self.response_task.done():
                await self.error("no active response to cancel")
                return
            self.response_task.cancel()
        else:
            await self.error(f"unsupported event type {kind!r}")

    async def _transcribe(self, audio: bytes) -> str | None:
        method = getattr(self.engine, "transcribe", None)
        if method is None:
            return None
        try:
            result = method(
                AudioTranscriptionRequest(
                    task="transcribe", file=audio, filename="realtime.pcm"
                )
            )
            if hasattr(result, "__await__"):
                result = await result
            text = getattr(result, "text", None)
            return str(text) if text else None
        except Exception:
            return None

    def _request(self, overrides: dict[str, Any]) -> ChatRequest:
        instructions = overrides.get("instructions", self.session.get("instructions", ""))
        tools = [
            payload
            for payload in (
                _tool_payload(tool) for tool in overrides.get("tools", self.session.get("tools", []))
            )
            if payload is not None
        ]
        raw_max = overrides.get(
            "max_output_tokens", self.session.get("max_response_output_tokens")
        )
        max_tokens = int(raw_max) if isinstance(raw_max, (int, float)) else 1024
        return ChatRequest(
            messages=_messages(self.items, str(instructions or "")),
            max_tokens=max_tokens,
            temperature=float(
                overrides.get("temperature", self.session.get("temperature", 0.8)) or 0.8
            ),
            stream=True,
            tools=tools or None,
            extras={
                "tool_choice": overrides.get(
                    "tool_choice", self.session.get("tool_choice", "auto")
                )
            },
        )

    async def _respond(self, overrides: dict[str, Any]) -> None:
        response: dict[str, Any] = {
            "id": new_id("resp"),
            "object": "realtime.response",
            "status": "in_progress",
            "status_details": None,
            "output": [],
            "usage": None,
        }
        self.response = response
        await self.send({"type": "response.created", "response": response})
        acquired = False
        try:
            await self.gate.acquire(response["id"])
            acquired = True
        except GpuBusyError:
            response["status"] = "failed"
            response["status_details"] = {
                "type": "failed",
                "error": {"type": "server_busy", "message": "GPU busy"},
            }
            await self.error("GPU busy", error_type="server_busy")
            await self.send({"type": "response.done", "response": response})
            return
        except asyncio.CancelledError:
            response["status"] = "cancelled"
            await self.send({"type": "response.done", "response": response})
            return

        text = ""
        text_item_id = new_id("item")
        text_index: int | None = None
        tool_calls: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        try:
            async for chunk in chat_chunks(self.engine, self._request(overrides)):
                if chunk.usage:
                    usage = dict(chunk.usage)
                if chunk.content_delta:
                    if text_index is None:
                        text_index = len(response["output"])
                        response["output"].append(
                            {
                                "id": text_item_id,
                                "type": "message",
                                "status": "in_progress",
                                "role": "assistant",
                                "content": [],
                            }
                        )
                        await self.send(
                            {
                                "type": "response.output_item.added",
                                "response_id": response["id"],
                                "output_index": text_index,
                                "item": response["output"][text_index],
                            }
                        )
                        await self.send(
                            {
                                "type": "response.content_part.added",
                                "response_id": response["id"],
                                "item_id": text_item_id,
                                "output_index": text_index,
                                "content_index": 0,
                                "part": {
                                    "type": "output_text",
                                    "text": "",
                                    "annotations": [],
                                },
                            }
                        )
                    text += chunk.content_delta
                    await self.send(
                        {
                            "type": "response.output_text.delta",
                            "response_id": response["id"],
                            "item_id": text_item_id,
                            "output_index": text_index,
                            "content_index": 0,
                            "delta": chunk.content_delta,
                        }
                    )
                for call in chunk.tool_calls or []:
                    function = call.get("function") if isinstance(call, dict) else None
                    if not isinstance(function, dict):
                        continue
                    item = {
                        "id": new_id("item"),
                        "type": "function_call",
                        "status": "completed",
                        "call_id": str(call.get("id") or new_id("call")),
                        "name": str(function.get("name", "")),
                        "arguments": function.get("arguments", ""),
                    }
                    tool_calls.append(item)
                    index = len(response["output"])
                    response["output"].append(item)
                    await self.send(
                        {
                            "type": "response.output_item.added",
                            "response_id": response["id"],
                            "output_index": index,
                            "item": item,
                        }
                    )
                    await self.send(
                        {
                            "type": "response.function_call_arguments.done",
                            "response_id": response["id"],
                            "item_id": item["id"],
                            "output_index": index,
                            "arguments": item["arguments"],
                        }
                    )
                    await self.send(
                        {
                            "type": "response.output_item.done",
                            "response_id": response["id"],
                            "output_index": index,
                            "item": item,
                        }
                    )
            if text_index is not None:
                item = response["output"][text_index]
                item["status"] = "completed"
                item["content"] = [
                    {"type": "output_text", "text": text, "annotations": []}
                ]
                await self.send(
                    {
                        "type": "response.output_text.done",
                        "response_id": response["id"],
                        "item_id": text_item_id,
                        "output_index": text_index,
                        "content_index": 0,
                        "text": text,
                    }
                )
                await self.send(
                    {
                        "type": "response.content_part.done",
                        "response_id": response["id"],
                        "item_id": text_item_id,
                        "output_index": text_index,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": text,
                            "annotations": [],
                        },
                    }
                )
                await self.send(
                    {
                        "type": "response.output_item.done",
                        "response_id": response["id"],
                        "output_index": text_index,
                        "item": item,
                    }
                )
            response["status"] = "completed"
            response["usage"] = usage or None
            for item in response["output"]:
                self.items.append(item)
            await self.send({"type": "response.done", "response": response})
        except asyncio.CancelledError:
            response["status"] = "cancelled"
            await self.send({"type": "response.done", "response": response})
            return
        except Exception as exc:
            response["status"] = "failed"
            response["status_details"] = {
                "type": "failed",
                "error": {"type": "api_error", "message": str(exc)},
            }
            await self.error(f"inference failed: {exc}", error_type="api_error")
            await self.send({"type": "response.done", "response": response})
        finally:
            if acquired:
                self.gate.release()


def mount(app: FastAPI, engine: Any, gate: InferenceGate) -> None:
    @app.websocket("/v1/realtime")
    async def realtime(websocket: WebSocket):
        model = websocket.query_params.get("model") or engine.model_id
        handler = getattr(engine, "realtime_session", None)
        if handler is not None:
            await websocket.accept()
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
            return
        await _RealtimeSession(websocket, engine, gate, model).run()
