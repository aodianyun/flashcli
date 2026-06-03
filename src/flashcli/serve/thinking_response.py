"""Split Qwen thinking output into OpenAI-compatible ``reasoning_content`` + ``content``."""

from __future__ import annotations

import re
from typing import Iterator

_THINKING_BLOCK_RE = re.compile(
    r"<think>(.*?)</think>\s*",
    re.DOTALL,
)


def split_reasoning_content(text: str | None) -> tuple[str | None, str | None]:
    """Extract thinking block and visible answer from model text.

    Qwen3.6 emits ``<think>...</think>`` when thinking
    mode is on. FlashRT leaves that in a single string; OpenAI-compat clients
    expect ``reasoning_content`` plus ``content``.
    """
    if not text:
        return None, text
    match = _THINKING_BLOCK_RE.search(text)
    if not match:
        return None, text
    reasoning = match.group(1).strip() or None
    content = _THINKING_BLOCK_RE.sub("", text, count=1).strip()
    return reasoning, content or None


class ThinkingStreamSplitter:
    """Incrementally split streamed text into reasoning vs answer deltas."""

    __slots__ = ("_buf", "_done_reasoning", "_enabled")

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self._buf = ""
        self._done_reasoning = not enabled

    def feed(self, text: str) -> Iterator[tuple[str, str]]:
        """Yield ``(\"reasoning_content\"|\"content\", delta_text)`` tuples."""
        if not text or not self._enabled:
            if text:
                yield ("content", text)
            return

        self._buf += text
        if self._done_reasoning:
            yield ("content", text)
            return

        while True:
            start = self._buf.find("<think>")
            if start == -1:
                # Hold partial tag prefix (e.g. "<redacted_think").
                hold = 0
                for i in range(min(len(self._buf), 18), 0, -1):
                    if "<think>"[:i] == self._buf[-i:]:
                        hold = i
                        break
                emit = self._buf[:-hold] if hold else self._buf
                if emit:
                    yield ("reasoning_content", emit)
                    self._buf = self._buf[-hold:] if hold else ""
                return

            if start > 0:
                prefix = self._buf[:start]
                yield ("reasoning_content", prefix)
                self._buf = self._buf[start:]

            end = self._buf.find("</think>")
            if end == -1:
                return

            inner_start = len("<think>")
            inner = self._buf[inner_start:end]
            if inner:
                yield ("reasoning_content", inner)
            self._buf = self._buf[end + len("</think>") :]
            # Skip whitespace between thinking block and answer.
            stripped = self._buf.lstrip()
            if stripped != self._buf and stripped:
                yield ("content", self._buf[: len(self._buf) - len(stripped)])
            self._buf = stripped
            self._done_reasoning = True
            if self._buf:
                yield ("content", self._buf)
                self._buf = ""
            return

    def flush(self) -> Iterator[tuple[str, str]]:
        if not self._buf:
            return
        field = "content" if self._done_reasoning else "reasoning_content"
        yield (field, self._buf)
        self._buf = ""
