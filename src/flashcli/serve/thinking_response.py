"""Split Qwen thinking output into OpenAI-compatible ``reasoning_content`` + ``content``."""

from __future__ import annotations

import re
from typing import Iterator

_THINKING_BLOCK_RE = re.compile(
    r"<think>(.*?)</think>\s*",
    re.DOTALL,
)
_THINKING_CLOSE = "</think>"


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)


def split_reasoning_content(
    text: str | None,
    *,
    enable_thinking: bool = False,
) -> tuple[str | None, str | None]:
    """Extract thinking block and visible answer from model text.

    Qwen3.6 opens the thinking block in the **prefill prompt**; the decode stream
    often contains only ``</think>`` plus the final answer.
    """
    if not text:
        return None, text
    match = _THINKING_BLOCK_RE.search(text)
    if match:
        reasoning = match.group(1).strip() or None
        content = _THINKING_BLOCK_RE.sub("", text, count=1).strip()
        return reasoning, content or None
    if _THINKING_CLOSE in text:
        reasoning, content = _split_at_thinking_close(text)
        if reasoning is not None or content is not None:
            return reasoning, content
    if not enable_thinking:
        return None, text
    return _split_without_visible_tags(text)


def _split_at_thinking_close(text: str) -> tuple[str | None, str | None]:
    """Split when only the closing think tag appears in generated text."""
    idx = text.find(_THINKING_CLOSE)
    if idx < 0:
        return None, None
    reasoning = text[:idx].strip() or None
    content = text[idx + len(_THINKING_CLOSE) :].strip() or None
    return reasoning, content


def _split_without_visible_tags(text: str) -> tuple[str | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, None
    parts = re.split(r"\n\n+", stripped, maxsplit=1)
    if len(parts) == 2 and _cjk_ratio(parts[1]) >= 0.15:
        head, tail = parts[0].strip(), parts[1].strip()
        return head or None, tail or None
    # Thinking-only generation (common when max_tokens cuts off before the answer).
    return stripped, None


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
                head, tail = parts[0], parts[1]
                if head:
                    yield ("reasoning_content", head)
                self._buf = ""
                self._done_reasoning = True
                if tail:
                    yield ("content", tail)
                return

        self._buf += text
        if self._done_reasoning:
            yield ("content", text)
            return

        while True:
            start = self._buf.find("<think>")
            if start == -1:
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
