"""Unified inference engine protocols for model bundles."""

from __future__ import annotations

from flashcli_bundle.protocol import (
    ChatChunk,
    ChatMessage,
    ChatRequest,
    AudioTranscriptionRequest,
    AudioTranscriptionResult,
    ChatResult,
    EmbeddingRequest,
    EmbeddingResult,
    ImageGenerationRequest,
    ImageGenerationResult,
    SpeechRequest,
    SpeechResult,
    RunEngine,
    ServeEngine,
    coerce_run_engine,
    coerce_serve_engine,
)
from flashcli_bundle.preset import Preset

__all__ = [
    "ChatChunk",
    "ChatMessage",
    "ChatRequest",
    "ChatResult",
    "AudioTranscriptionRequest",
    "AudioTranscriptionResult",
    "EmbeddingRequest",
    "EmbeddingResult",
    "ImageGenerationRequest",
    "ImageGenerationResult",
    "SpeechRequest",
    "SpeechResult",
    "Preset",
    "RunEngine",
    "ServeEngine",
    "coerce_run_engine",
    "coerce_serve_engine",
]
