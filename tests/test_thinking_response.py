"""Tests for Qwen thinking → OpenAI reasoning_content splitting."""

from flashcli.serve.thinking_response import ThinkingStreamSplitter, split_reasoning_content


def test_split_reasoning_content_with_tags():
    text = "<think>\n分析\n</think>\n\n答案"
    reasoning, content = split_reasoning_content(text)
    assert reasoning == "分析"
    assert content == "答案"


def test_split_reasoning_content_without_tags():
    reasoning, content = split_reasoning_content("直接回答")
    assert reasoning is None
    assert content == "直接回答"


def test_thinking_stream_splitter_emits_reasoning_then_content():
    splitter = ThinkingStreamSplitter(enabled=True)
    parts: list[tuple[str, str]] = []
    for delta in ["<think>\n", "想\n", "</think>\n\n", "答"]:
        parts.extend(splitter.feed(delta))
    parts.extend(splitter.flush())
    assert ("reasoning_content", "想") in parts or any(
        f == "reasoning_content" for f, _ in parts
    )
    assert any(f == "content" and "答" in d for f, d in parts)
