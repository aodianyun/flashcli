"""Tests for enable_thinking resolution in flashcli serve request logs."""

from flashcli.engines.base import ChatMessage, ChatRequest
from flashcli.serve.request_log import (
    DEFAULT_ENABLE_THINKING,
    apply_enable_thinking_to_openai_payload,
    format_enable_thinking,
    resolve_enable_thinking,
    summarize_chat_body,
)


def test_resolve_enable_thinking_defaults_true():
    assert DEFAULT_ENABLE_THINKING is True
    assert resolve_enable_thinking({}) == (True, None)


def test_resolve_enable_thinking_top_level():
    assert resolve_enable_thinking({"enable_thinking": True}) == (True, "body")
    assert resolve_enable_thinking({"enable_thinking": "false"}) == (False, "body")


def test_resolve_enable_thinking_chat_template_kwargs():
    body = {"chat_template_kwargs": {"enable_thinking": True}}
    assert resolve_enable_thinking(body) == (True, "chat_template_kwargs")


def test_resolve_enable_thinking_body_overrides_kwargs():
    body = {
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert resolve_enable_thinking(body) == (False, "body")


def test_summarize_chat_body_includes_enable_thinking():
    summary = summarize_chat_body(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "chat_template_kwargs": {"enable_thinking": True},
        }
    )
    assert "enable_thinking=true(src=chat_template_kwargs)" in summary


def test_format_enable_thinking_default():
    assert format_enable_thinking({}) == "enable_thinking=true"


def test_resolve_enable_thinking_explicit_false():
    assert resolve_enable_thinking({"enable_thinking": False}) == (False, "body")
    body = {"chat_template_kwargs": {"enable_thinking": False}}
    assert resolve_enable_thinking(body) == (False, "chat_template_kwargs")


def test_apply_enable_thinking_hoists_chat_template_kwargs():
    payload: dict = {
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert apply_enable_thinking_to_openai_payload(payload) is True
    assert payload["enable_thinking"] is True


def test_chat_request_to_openai_body_hoists_for_flashrt():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "bundles/qwen_nvfp4/_qwen_util.py"
    spec = importlib.util.spec_from_file_location("bundle_qwen_util_think_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
        extras={"chat_template_kwargs": {"enable_thinking": True}},
    )
    body = mod.chat_request_to_openai_body(req)
    assert body["enable_thinking"] is True


def test_chat_request_to_openai_body_defaults_true_without_extras():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "bundles/qwen_nvfp4/_qwen_util.py"
    spec = importlib.util.spec_from_file_location("bundle_qwen_util_think_default", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=64,
    )
    body = mod.chat_request_to_openai_body(req)
    assert body["enable_thinking"] is True
