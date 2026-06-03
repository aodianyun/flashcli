"""Tests for Qwen3.6 bundle-local thinking → OpenAI field mapping."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from flashcli.engines.base import ChatMessage, ChatRequest


def _qwen36_thinking():
    path = Path(__file__).resolve().parents[1] / "bundles/qwen_nvfp4/_qwen36_thinking.py"
    spec = importlib.util.spec_from_file_location("bundle_qwen36_thinking_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_split_at_closing_tag_only():
    mod = _qwen36_thinking()
    text = "think</think>\n\nanswer"
    reasoning, content = mod.split_qwen36_assistant_text(text, enable_thinking=True)
    assert reasoning == "think"
    assert content == "answer"


def test_enable_thinking_from_request_extras():
    mod = _qwen36_thinking()
    req = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        extras={"enable_thinking": False},
    )
    assert mod.enable_thinking_from_request(req) is False
