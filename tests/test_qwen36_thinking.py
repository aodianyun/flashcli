"""Tests for Qwen3.6 bundle-local thinking → OpenAI field mapping."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from flashcli_bundle.protocol import ChatMessage, ChatRequest


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


def test_split_thought_close_tag():
    mod = _qwen36_thinking()
    text = "draft</thought>\n\n正文"
    reasoning, content = mod.split_qwen36_assistant_text(text, enable_thinking=True)
    assert reasoning == "draft"
    assert content == "正文"


def test_no_close_tag_all_reasoning_when_thinking():
    mod = _qwen36_thinking()
    reasoning, content = mod.split_qwen36_assistant_text(
        "English draft\n\n中文还在思考",
        enable_thinking=True,
    )
    assert reasoning == "English draft\n\n中文还在思考"
    assert content is None


def test_stream_does_not_split_without_close_tag():
    mod = _qwen36_thinking()
    splitter = mod.Qwen36ThinkingStreamSplitter(enabled=True)
    chunks = list(splitter.feed("English draft\n\n中文还在思考"))
    assert chunks
    assert all(field == "reasoning_content" for field, _ in chunks)
    assert splitter._done_reasoning is False


def test_enable_thinking_from_request_extras():
    mod = _qwen36_thinking()
    req = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        extras={"enable_thinking": False},
    )
    assert mod.enable_thinking_from_request(req) is False
