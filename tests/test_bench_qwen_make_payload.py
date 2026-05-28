"""Tests for long-prompt fitting in bench_qwen_make_payload.py."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import bench_qwen_make_payload as bmp  # noqa: E402


class _TensorShape:
    def __init__(self, n: int) -> None:
        self.shape = (1, n)


class _LinearTokenizer:
    """One token per character; fixed chat-template overhead."""

    template_overhead = 12

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(range(len(text)))

    def apply_chat_template(self, messages, **kwargs) -> str:
        return messages[0]["content"]

    def __call__(self, prompt: str, return_tensors: str = "pt"):
        n = len(prompt) + self.template_overhead
        return type("Out", (), {"input_ids": _TensorShape(n)})()


class _ShrinkDecodeTokenizer(_LinearTokenizer):
    """Simulate decode(ids) losing ~17% tokens at long lengths (qwen36 flashrt path)."""

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        if len(ids) <= 64:
            return "x" * len(ids)
        shrunk = max(1, (len(ids) * 218454) // 262144)
        return "x" * shrunk


def test_build_prompt_reaches_target_without_decode_roundtrip():
    tok = _LinearTokenizer()
    _text, actual = bmp.build_prompt_text(tok, 500, "seed")
    assert 480 <= actual <= 500


def test_fit_fills_rendered_budget_not_early_exit():
    tok = _LinearTokenizer()
    budget = 1000 - 64 - 32
    _text, _actual, rendered = bmp.fit_user_prompt_to_budget(
        tok,
        target_user_tokens=10_000,
        max_seq=1000,
        max_tokens=64,
        seed="ab",
        seq_slack=32,
    )
    assert rendered <= budget
    assert rendered >= budget - 20


def test_decode_roundtrip_no_longer_caps_near_218k():
    """Old ids→decode→encode path plateaued ~218K; string repeat must exceed that."""
    tok = _ShrinkDecodeTokenizer()
    _text, actual = bmp.build_prompt_text(tok, 250_000, "Explain quantum entanglement in one short paragraph. ")
    assert actual >= 240_000
