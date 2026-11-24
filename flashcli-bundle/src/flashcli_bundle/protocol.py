"""Inference engine protocols and chat datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable

from flashcli_bundle.preset import Preset


@dataclass
class ChatMessage:
    role: str
    content: str | list | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    reasoning_content: str | None = None


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
class ModerationRequest:
    input: list[str]
    model: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModerationResult:
    results: list[dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoRequest:
    prompt: str
    model: str = ""
    seconds: int | None = None
    size: str | None = None
    input_reference: bytes | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoJob:
    id: str
    status: str = "queued"
    progress: float = 0.0
    created_at: int = 0
    completed_at: int | None = None
    expires_at: int | None = None
    model: str = ""
    error: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioTranscriptionRequest:
    task: str = "transcribe"  # transcribe | translate
    file: bytes = b""
    filename: str = "audio"
    model: str = ""
    language: str | None = None
    prompt: str | None = None
    response_format: str = "json"
    temperature: float | None = None
    timestamp_granularities: list[str] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioTranscriptionResult:
    text: str
    language: str | None = None
    duration: float | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpeechRequest:
    input: str
    model: str = ""
    voice: str = "alloy"
    response_format: str = "mp3"
    speed: float = 1.0
    instructions: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpeechResult:
    audio: bytes
    media_type: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGenerationRequest:
    prompt: str
    model: str = ""
    mode: str = "generate"  # generate | edit | variation
    n: int = 1
    size: str = "1024x1024"
    quality: str = "auto"
    style: str | None = None
    response_format: str = "url"  # url | b64_json
    images: list[bytes] = field(default_factory=list)
    mask: bytes | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGenerationResult:
    images: list[bytes | str]
    response_format: str = "url"
    revised_prompt: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    media_type: str = "image/png"


@dataclass
class EmbeddingRequest:
    input: list[str] | list[list[int]]
    model: str = ""
    dimensions: int | None = None
    encoding_format: str = "float"
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    embeddings: list[list[float]]
    usage: dict[str, Any] = field(default_factory=dict)


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


_CHAT_SERVE_CAPABILITIES = frozenset(
    {"openai.chat", "openai.completions", "openai.responses", "anthropic.messages"}
)

# Declared modality capabilities require their engine methods at load time; a
# bundle that declares a route without implementing it fails serve startup
# instead of returning 501 for every request.
_CAPABILITY_METHODS: dict[str, tuple[str, ...]] = {
    "openai.embeddings": ("embed",),
    "openai.moderations": ("moderate",),
    "openai.audio.transcriptions": ("transcribe",),
    "openai.audio.translations": ("transcribe",),
    "openai.audio.speech": ("speech",),
    "openai.images.generations": ("generate_images",),
    "openai.images.edits": ("generate_images",),
    "openai.images.variations": ("generate_images",),
    "openai.videos": (
        "create_video",
        "list_videos",
        "get_video",
        "download_video",
        "delete_video",
    ),
    "anthropic.count_tokens": ("count_tokens",),
}


def coerce_serve_engine(
    obj: Any,
    *,
    capabilities: list[str] | None = None,
) -> ServeEngine:
    """Validate a serve engine against the capabilities it must implement.

    ``model_id``/``load``/``warmup`` are always required. ``chat``/``chat_stream``
    are required only when a chat-based capability is declared (or realtime is
    declared without a bundle ``realtime_session`` handler). Every declared
    modality capability also requires its engine method(s); missing members fail
    serve startup.
    """
    required = ["model_id", "load", "warmup"]
    needs_chat = capabilities is None or any(
        cap in _CHAT_SERVE_CAPABILITIES for cap in capabilities
    )
    if (
        capabilities is not None
        and "openai.realtime" in capabilities
        and not hasattr(obj, "realtime_session")
    ):
        needs_chat = True
    if needs_chat:
        required.extend(["chat", "chat_stream"])
    for cap in capabilities or ():
        required.extend(_CAPABILITY_METHODS.get(cap, ()))
    required = list(dict.fromkeys(required))
    missing = [name for name in required if not hasattr(obj, name)]
    if missing:
        raise TypeError(
            f"Serve engine is missing required members {missing}: {type(obj)!r}"
        )
    return obj
