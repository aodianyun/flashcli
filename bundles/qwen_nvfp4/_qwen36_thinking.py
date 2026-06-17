"""Qwen3.6-only helpers: map FlashRT decoded text to OpenAI reasoning fields.

FlashRT ``qwen36_agent`` currently returns one visible ``text`` stream. For
thinking mode the model emits a closing tag before the user-facing answer
(``</think>`` or ``</thought>``; opening tag is often in prefill).
This module is **bundle-local** — ``flashcli_bundle.infer.serve`` only forwards
``ChatResult.reasoning_content`` / ``ChatChunk.reasoning_delta`` when the bundle
sets them. When FlashRT grows native reasoning SSE, replace the implementation
here and keep the serve contract unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

from flashcli_bundle.protocol import ChatRequest
from flashcli_bundle.openai_compat import resolve_enable_thinking

log = logging.getLogger(__name__)

# Decoded close markers (longest first for suffix hold).
_THINKING_CLOSE_MARKERS: tuple[str, ...] = (
    "</think>",
    "</thought>",
)
_THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?thinking>(.*?)</(?:redacted_)?thinking>\s*",
    re.DOTALL,
)


def enable_thinking_from_request(req: ChatRequest) -> bool:
    return resolve_enable_thinking(dict(req.extras or {}))[0]


def _find_earliest_close(text: str) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for marker in _THINKING_CLOSE_MARKERS:
        idx = text.find(marker)
        if idx >= 0 and (best is None or idx < best[0]):
            best = (idx, marker)
    return best


def _strip_open_thinking_tags(text: str) -> str:
    return re.sub(r"</?(?:redacted_)?thinking>", "", text).strip()


def split_qwen36_assistant_text(
    text: str | None,
    *,
    enable_thinking: bool,
) -> tuple[str | None, str | None]:
    """Return ``(reasoning_content, content)`` for OpenAI-shaped responses."""
    if not text:
        return None, text
    match = _THINKING_BLOCK_RE.search(text)
    if match:
        reasoning = match.group(1).strip() or None
        content = _THINKING_BLOCK_RE.sub("", text, count=1).strip()
        return reasoning, content or None
    found = _find_earliest_close(text)
    if found:
        idx, marker = found
        reasoning = _strip_open_thinking_tags(text[:idx]) or None
        content = text[idx + len(marker) :].strip() or None
        return reasoning, content
    if not enable_thinking:
        return None, text
    stripped = text.strip()
    return stripped or None, None


def _hold_suffix_len(buf: str) -> int:
    hold = 0
    for marker in _THINKING_CLOSE_MARKERS:
        for i in range(min(len(buf), len(marker)), 0, -1):
            if marker[:i] == buf[-i:]:
                hold = max(hold, i)
    return hold


class Qwen36ThinkingStreamSplitter:
    """Incremental split for Qwen3.6 SSE; only explicit close tags."""

    __slots__ = ("_buf", "_done_reasoning", "_enabled")

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self._buf = ""
        self._done_reasoning = not enabled

    def feed(self, text: str) -> Iterator[tuple[str, str]]:
        if not text or not self._enabled:
            if text:
                yield ("content", text)
            return

        if self._done_reasoning:
            yield ("content", text)
            return

        combined = self._buf + text
        found = _find_earliest_close(combined)
        if found:
            idx, marker = found
            head = _strip_open_thinking_tags(combined[:idx])
            tail = combined[idx + len(marker) :].lstrip()
            if head:
                yield ("reasoning_content", head)
            self._buf = ""
            self._done_reasoning = True
            if tail:
                yield ("content", tail)
            return

        self._buf = combined
        hold = _hold_suffix_len(self._buf)
        emit = self._buf[:-hold] if hold else self._buf
        if emit:
            yield ("reasoning_content", emit)
            self._buf = self._buf[-hold:] if hold else ""

    def flush(self) -> Iterator[tuple[str, str]]:
        if not self._buf:
            return
        field = "content" if self._done_reasoning else "reasoning_content"
        text = self._buf
        if field == "reasoning_content":
            text = _strip_open_thinking_tags(text)
        if text:
            yield (field, text)
        self._buf = ""
