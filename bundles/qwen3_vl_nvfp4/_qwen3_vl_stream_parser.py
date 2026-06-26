"""Streaming helpers for Qwen3-VL bundle (tool-call parse + sampling)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

_TOOL_CALL_OPEN = "<tool_call>"
_TOOL_CALL_CLOSE = "</tool_call>"


def sample_token(
    logits,
    *,
    temperature: float,
    top_p: float,
    top_k: int,
    rng=None,
) -> int:
    """Greedy if temperature == 0, else top-k + top-p multinomial."""
    import torch

    if temperature <= 0.0 or top_k == 1:
        return int(logits.argmax(dim=-1).item())

    scaled = logits.float() / max(temperature, 1e-6)
    if top_k and 0 < top_k < scaled.numel():
        topv, topi = torch.topk(scaled, top_k)
        mask = torch.full_like(scaled, float("-inf"))
        mask.scatter_(0, topi, topv)
        scaled = mask

    if 0.0 < top_p < 1.0:
        sorted_v, sorted_idx = torch.sort(scaled, descending=True)
        sorted_p = torch.softmax(sorted_v, dim=-1)
        cum = sorted_p.cumsum(dim=-1)
        cutoff_mask = cum > top_p
        cutoff_mask[..., 1:] = cutoff_mask[..., :-1].clone()
        cutoff_mask[..., 0] = False
        sorted_v[cutoff_mask] = float("-inf")
        scaled = torch.full_like(scaled, float("-inf"))
        scaled.scatter_(0, sorted_idx, sorted_v)

    probs = torch.softmax(scaled, dim=-1)
    if rng is not None:
        return int(torch.multinomial(probs, 1, generator=rng).item())
    return int(torch.multinomial(probs, 1).item())


class StreamParser:
    """Split assistant tokens into content deltas and OpenAI tool_calls."""

    def __init__(
        self,
        tokenizer: Any,
        *,
        stop_strings: list[str] | None = None,
        enable_tools: bool = False,
    ) -> None:
        self.tok = tokenizer
        self._buffer = ""
        self._in_tool = False
        self._tool_buffer = ""
        self._stop_strings = stop_strings or []
        self._enable_tools = bool(enable_tools)
        self._tool_calls_emitted: list[dict[str, Any]] = []
        self._tool_call_idx = 0

    def feed(
        self,
        new_token_ids: list[int],
        *,
        final: bool = False,
    ) -> tuple[str, list[dict[str, Any]], bool]:
        if new_token_ids:
            try:
                fragment = self.tok.decode(new_token_ids, skip_special_tokens=False)
            except Exception:
                fragment = ""
            self._buffer += fragment

        delta_text = ""
        new_tool_calls: list[dict[str, Any]] = []
        stop_hit = False

        if self._stop_strings and not self._in_tool:
            best_idx = -1
            for ss in self._stop_strings:
                idx = self._buffer.find(ss)
                if idx >= 0 and (best_idx < 0 or idx < best_idx):
                    best_idx = idx
            if best_idx >= 0:
                self._buffer = self._buffer[:best_idx]
                stop_hit = True

        max_stop_len = (
            max((len(s) for s in self._stop_strings), default=0)
            if self._stop_strings
            else 0
        )
        hold = (
            0
            if (final or stop_hit)
            else max(
                len(_TOOL_CALL_OPEN) if self._enable_tools else 0,
                max_stop_len,
            )
            - 1
        )
        hold = max(0, hold)

        while True:
            if self._in_tool:
                close_idx = self._buffer.find(_TOOL_CALL_CLOSE)
                if close_idx < 0:
                    self._tool_buffer += self._buffer
                    self._buffer = ""
                    break
                self._tool_buffer += self._buffer[:close_idx]
                self._buffer = self._buffer[close_idx + len(_TOOL_CALL_CLOSE) :]
                self._in_tool = False
                tc = self._parse_tool_call(self._tool_buffer.strip())
                self._tool_buffer = ""
                if tc is not None:
                    new_tool_calls.append(tc)
                    self._tool_calls_emitted.append(tc)
                continue

            open_idx = (
                self._buffer.find(_TOOL_CALL_OPEN) if self._enable_tools else -1
            )
            if open_idx < 0:
                safe = max(0, len(self._buffer) - hold)
                if safe > 0:
                    delta_text += self._buffer[:safe]
                    self._buffer = self._buffer[safe:]
                break
            delta_text += self._buffer[:open_idx]
            self._buffer = self._buffer[open_idx + len(_TOOL_CALL_OPEN) :]
            self._in_tool = True

        return delta_text, new_tool_calls, stop_hit

    def _parse_tool_call(self, raw: str) -> dict[str, Any] | None:
        s = raw.strip()
        if s.startswith("```"):
            s = re.sub(r"^```[^\n]*\n", "", s)
            if s.endswith("```"):
                s = s[:-3]
            s = s.strip()
        try:
            obj = json.loads(s)
        except Exception:
            return None
        name = obj.get("name")
        args = obj.get("arguments", obj.get("parameters", {}))
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        idx = self._tool_call_idx
        self._tool_call_idx += 1
        return {
            "index": idx,
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {"name": name, "arguments": args},
        }
