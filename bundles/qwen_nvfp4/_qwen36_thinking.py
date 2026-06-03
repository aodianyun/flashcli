"""Qwen3.6-only helpers: map FlashRT decoded text to OpenAI reasoning fields.

FlashRT ``qwen36_agent`` currently returns one visible ``text`` stream. For
thinking mode the model often emits a closing ``</think>`` marker
before the user-facing answer (opening tag lives in the prefill template, not
in decode output). This module is **bundle-local** — ``flashcli.serve`` only
forwards ``ChatResult.reasoning_content`` / ``ChatChunk.reasoning_delta`` when
the bundle sets them. When FlashRT grows native reasoning SSE, replace the
implementation here and keep the serve contract unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Iterator

from flashcli.engines.base import ChatRequest

log = logging.getLogger(__name__)

_THINKING_BLOCK_RE = re.compile(
    r"<think>(.*?)</think>\s*",
    re.DOTALL,
)
_THINKING_CLOSE = "</think>"


def enable_thinking_from_request(req: ChatRequest) -> bool:
    from flashcli.serve.request_log import resolve_enable_thinking

    return resolve_enable_thinking(dict(req.extras or {}))[0]


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
    if _THINKING_CLOSE in text:
        idx = text.find(_THINKING_CLOSE)
        reasoning = text[:idx].strip() or None
        content = text[idx + len(_THINKING_CLOSE) :].strip() or None
        return reasoning, content
    if not enable_thinking:
        return None, text
    return _split_heuristic(text)


def _split_heuristic(text: str) -> tuple[str | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, None
    parts = re.split(r"\n\n+", stripped, maxsplit=1)
    if len(parts) == 2 and _cjk_ratio(parts[1]) >= 0.15:
        return parts[0].strip() or None, parts[1].strip() or None
    return stripped, None


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)


class Qwen36ThinkingStreamSplitter:
    """Incremental split for Qwen3.6 SSE bridged through the bundle."""

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

        if not self._done_reasoning:
            combined = self._buf + text
            close_at = combined.find(_THINKING_CLOSE)
            if close_at >= 0:
                head = combined[:close_at]
                tail = combined[close_at + len(_THINKING_CLOSE) :].lstrip()
                if head:
                    yield ("reasoning_content", head)
                self._buf = ""
                self._done_reasoning = True
                if tail:
                    yield ("content", tail)
                return
            parts = re.split(r"\n\n+", combined, maxsplit=1)
            if len(parts) == 2 and _cjk_ratio(parts[1]) >= 0.15:
                if parts[0]:
                    yield ("reasoning_content", parts[0])
                self._buf = ""
                self._done_reasoning = True
                if parts[1]:
                    yield ("content", parts[1])
                return

        self._buf += text
        hold = 0
        for i in range(min(len(self._buf), len(_THINKING_CLOSE)), 0, -1):
            if _THINKING_CLOSE[:i] == self._buf[-i:]:
                hold = i
                break
        emit = self._buf[:-hold] if hold else self._buf
        if emit:
            yield ("reasoning_content", emit)
            self._buf = self._buf[-hold:] if hold else ""

    def flush(self) -> Iterator[tuple[str, str]]:
        if not self._buf:
            return
        field = "content" if self._done_reasoning else "reasoning_content"
        yield (field, self._buf)
        self._buf = ""
