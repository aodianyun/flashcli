"""Inference engine protocols and chat datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable

from flashcli_bundle.preset import Preset


@dataclass
class ChatMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    max_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    stop: list[str] | None = None
    seed: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatChunk:
    content_delta: str = ""
    reasoning_delta: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@runtime_checkable
class RunEngine(Protocol):
    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None: ...

    def predict(
        self,
        *,
        prompt: str = "",
        images: list[Any] | None = None,
        **kwargs: Any,
    ) -> Any: ...


@runtime_checkable
class ServeEngine(Protocol):
    @property
    def model_id(self) -> str: ...

    def load(self, checkpoint: Path, preset: Preset, **options: Any) -> None: ...

    def warmup(self, spec: str | None) -> None: ...

    def chat(self, request: ChatRequest) -> ChatResult: ...

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]: ...


def coerce_run_engine(obj: Any) -> RunEngine:
    if not isinstance(obj, RunEngine):
        raise TypeError(
            f"Run engine must implement RunEngine protocol, got {type(obj)!r}"
        )
    return obj


def coerce_serve_engine(obj: Any) -> ServeEngine:
    if not isinstance(obj, ServeEngine):
        raise TypeError(
            f"Serve engine must implement ServeEngine protocol, got {type(obj)!r}"
        )
    return obj
