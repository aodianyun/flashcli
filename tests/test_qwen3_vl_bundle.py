"""Unit tests for qwen3_vl_nvfp4 bundle (no GPU required)."""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

BUNDLE_ROOT = Path(__file__).resolve().parents[1] / "bundles" / "qwen3_vl_nvfp4"


@pytest.fixture(scope="module", autouse=True)
def _bundle_on_path() -> None:
    root = str(BUNDLE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def test_manifest_validate_options() -> None:
    from flashcli.bundle.manifest import load_bundle_manifest
    from flashcli_bundle.infer.cli import validate_bundle_options

    manifest = load_bundle_manifest(BUNDLE_ROOT)
    assert manifest.name == "qwen3_vl_nvfp4"
    assert validate_bundle_options(manifest) == []


def test_openai_messages_to_frontend_text() -> None:
    from _qwen3_vl_util_messages import openai_messages_to_frontend

    out = openai_messages_to_frontend(
        [{"role": "user", "content": "hello"}],
    )
    assert out == [{"role": "user", "content": "hello"}]


def test_openai_messages_to_frontend_image_url(tmp_path: Path) -> None:
    from _qwen3_vl_util_messages import openai_messages_to_frontend

    img_path = tmp_path / "scene.png"
    Image.new("RGB", (8, 8), color=(255, 0, 0)).save(img_path)
    out = openai_messages_to_frontend(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what color?"},
                    {"type": "image_url", "image_url": {"url": str(img_path)}},
                ],
            }
        ],
    )
    assert out[0]["role"] == "user"
    parts = out[0]["content"]
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image"
    assert hasattr(parts[1]["image"], "size")


def test_openai_messages_to_frontend_data_url() -> None:
    from _qwen3_vl_util_messages import openai_messages_to_frontend

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(0, 128, 255)).save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    out = openai_messages_to_frontend(
        [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": data_url}}],
            }
        ],
    )
    assert out[0]["content"][0]["type"] == "image"


def test_run_messages_from_prompt_image(tmp_path: Path) -> None:
    from _qwen3_vl_util_messages import run_messages_from_prompt_image

    img_path = tmp_path / "a.jpg"
    Image.new("RGB", (16, 16)).save(img_path)
    msgs = run_messages_from_prompt_image("describe", str(img_path))
    assert msgs[0]["role"] == "user"
    assert len(msgs[0]["content"]) == 2


def test_run_messages_text_only() -> None:
    from _qwen3_vl_util import build_run_request

    messages, gen_kw = build_run_request(
        [],
        defaults={"max_tokens": 32, "temperature": 0.0, "top_p": 1.0, "top_k": 0},
        merged={"prompt": "你好"},
    )
    assert messages == [{"role": "user", "content": "你好"}]
    assert gen_kw["max_tokens"] == 32


def test_run_engine_predict_accepts_image_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run as run_mod

    img_path = tmp_path / "test.png"
    Image.new("RGB", (8, 8)).save(img_path)
    captured: dict[str, object] = {}

    def fake_build(_msgs, *, defaults, merged):
        captured.update(merged)
        return [], {
            "max_tokens": 1,
            "temperature": 0.0,
            "top_p": 1.0,
            "top_k": 0,
        }

    class FakeEngine:
        async def stream_generate(self, *_a, **_k):
            if False:
                yield ("finish", "stop", {})

    monkeypatch.setattr(run_mod, "build_run_request", fake_build)
    monkeypatch.setattr(run_mod, "run_async", lambda _coro: {"text": ""})

    engine = run_mod.RunEngine()
    engine._engine = FakeEngine()
    engine._run_defaults = {}
    engine.predict(prompt="describe", image_paths=[img_path], echo=False)
    assert captured.get("image") == str(img_path)


def test_bundle_modules_import() -> None:
    from _qwen3_vl_stream_parser import StreamParser, sample_token

    assert StreamParser is not None
    assert sample_token is not None

    pytest.importorskip("flash_rt")
    import run  # noqa: F401
    import serve  # noqa: F401
    from _backend_qwen3_vl import Qwen3VlBackend
    from _engine_qwen3_vl import Qwen3VlEngine

    assert Qwen3VlBackend is not None
    assert Qwen3VlEngine is not None
