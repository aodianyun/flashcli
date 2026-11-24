"""Real ServeEngine-mode bundle acceptance for OpenAI/Anthropic protocols.

Builds deterministic-but-realistic bundles for LLM, code, ASR, TTS, combined
audio, image, video, Anthropic-only, and legacy manifests, starts each through
``python -m flashcli_bundle.infer serve``, and exercises the host-owned
protocol surface over real sockets.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
httpx = pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SRC = ROOT / "flashcli-bundle" / "src"
ACCEPTANCE_DIR = Path(__file__).resolve().parent
ENV_KEY = "test-linux-x86_64-py312"

LLM_CAPS = [
    "openai.chat",
    "openai.completions",
    "openai.responses",
    "openai.embeddings",
    "openai.moderations",
    "openai.realtime",
    "anthropic.messages",
    "anthropic.count_tokens",
    "anthropic.models",
]
CODE_CAPS = ["openai.chat", "openai.completions", "openai.responses"]
ANTHROPIC_CAPS = ["anthropic.messages", "anthropic.count_tokens", "anthropic.models"]
ASR_CAPS = ["openai.audio.transcriptions", "openai.audio.translations"]
TTS_CAPS = ["openai.audio.speech"]
AUDIO_CAPS = [
    "openai.audio.transcriptions",
    "openai.audio.translations",
    "openai.audio.speech",
]
IMAGE_CAPS = [
    "openai.images.generations",
    "openai.images.edits",
    "openai.images.variations",
]
VIDEO_CAPS = ["openai.videos"]

BUNDLES: dict[str, tuple[list[str] | None, str]] = {
    "llm": (LLM_CAPS, "LLMEngine"),
    "code": (CODE_CAPS, "CodeEngine"),
    "anthropic": (ANTHROPIC_CAPS, "LLMEngine"),
    "asr": (ASR_CAPS, "ASREngine"),
    "tts": (TTS_CAPS, "TTSEngine"),
    "audio": (AUDIO_CAPS, "AudioEngine"),
    "image": (IMAGE_CAPS, "ImageEngine"),
    "video": (VIDEO_CAPS, "VideoEngine"),
    "legacy": (None, "LLMEngine"),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_bundle(
    path: Path,
    kind: str,
    caps: list[str] | None,
    engine_class: str,
    *,
    mode: str = "engine",
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "kind": "python",
        "module": "serve",
        "attr": "ServeEngine" if mode == "engine" else "main",
        "mode": mode,
    }
    if caps is not None:
        entry["capabilities"] = caps
    manifest = {
        "format": "flashcli-model-bundle",
        "format_version": 4,
        "protocol_version": 1,
        "name": f"serve_{kind}",
        "description": f"Serve acceptance fixture: {kind}.",
        "defaults": {
            "entry": {"serve": entry},
            "python_abi": "312",
            "python_dependencies": {"torch": False, "pip": []},
            "serve_options": [
                {
                    "name": "warmup",
                    "type": "string",
                    "help": "Warmup spec.",
                    "phase": "warmup",
                }
            ],
        },
        "environments": {ENV_KEY: {"runtime": "runtime/test"}},
    }
    (path / "flashcli-bundle.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    if mode == "engine":
        (path / "serve.py").write_text(
            f"from serve_fixture_engines import {engine_class} as ServeEngine\n",
            encoding="utf-8",
        )
    else:
        (path / "serve.py").write_text(
            "def main(argv=None):\n    return 0\n", encoding="utf-8"
        )
    (path / "runtime" / "test").mkdir(parents=True, exist_ok=True)
    (path / "checkpoint").mkdir(parents=True, exist_ok=True)
    (path / "checkpoint" / "model.safetensors").write_bytes(b"")
    return path


def _start(bundle: Path, log_dir: Path) -> dict[str, Any]:
    port = _free_port()
    env = dict(os.environ)
    paths = [str(BUNDLE_SRC), str(ACCEPTANCE_DIR)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["FLASHCLI_NO_MIRROR"] = "1"
    env["FLASHCLI_RUNTIME_ENV_KEY"] = ENV_KEY
    env["PYTHONUNBUFFERED"] = "1"
    log_path = log_dir / f"{bundle.name}.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "flashcli_bundle.infer",
            "serve",
            str(bundle),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--checkpoint",
            str(bundle / "checkpoint"),
            "--no-auto-install",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 25
    with httpx.Client(timeout=1.0) as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                if client.get(f"{base}/health").status_code == 200:
                    return {
                        "proc": proc,
                        "base": base,
                        "log": log_path,
                        "log_file": log_file,
                        "port": port,
                    }
            except httpx.HTTPError:
                pass
            time.sleep(0.15)
    log_file.close()
    output = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    raise AssertionError(f"server {bundle.name} failed to start:\n{output[-4000:]}")


def _stop(server: dict[str, Any]) -> None:
    proc = server["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    server["log_file"].close()


def _sse_payloads(raw: str):
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload.strip() == "[DONE]":
            continue
        yield json.loads(payload)


def _chat_text(raw: str) -> str:
    text = ""
    for payload in _sse_payloads(raw):
        for choice in payload.get("choices", []):
            text += choice.get("delta", {}).get("content") or ""
    return text


def _anthropic_events(raw: str) -> list[str]:
    return [
        line.removeprefix("event: ")
        for line in raw.splitlines()
        if line.startswith("event: ")
    ]


@pytest.fixture(scope="session")
def serve_bundles(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("serve_bundles")
    built = {
        kind: _write_bundle(root / kind, kind, caps, engine_class)
        for kind, (caps, engine_class) in BUNDLES.items()
    }
    servers: dict[str, dict[str, Any]] = {}
    try:
        for kind, path in built.items():
            servers[kind] = _start(path, root)
        yield {"built": built, "servers": servers}
    finally:
        for server in servers.values():
            _stop(server)


def test_fixture_bundles_validate(serve_bundles, flashcli_bin) -> None:
    for kind, path in serve_bundles["built"].items():
        proc = subprocess.run(
            [str(flashcli_bin), "bundle", "validate", str(path)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"{kind}:\n{proc.stdout}\n{proc.stderr}"


def test_script_mode_rejects_capabilities(tmp_path: Path, flashcli_bin) -> None:
    path = _write_bundle(
        tmp_path / "script_caps", "script_caps", ["openai.chat"], "LLMEngine", mode="script"
    )
    proc = subprocess.run(
        [str(flashcli_bin), "bundle", "validate", str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "only valid for python engine serve" in (proc.stdout + proc.stderr)


def test_llm_openai_surface(serve_bundles) -> None:
    base = serve_bundles["servers"]["llm"]["base"]
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}]
    with httpx.Client(timeout=10.0) as client:
        assert client.get(f"{base}/health").json()["model"] == "llm-fixture"
        assert client.get(f"{base}/v1/models").json()["object"] == "list"
        assert client.get(f"{base}/v1/models/llm-fixture").json()["object"] == "model"
        assert client.get(f"{base}/v1/models/missing").json()["error"]["code"] == "model_not_found"

        chat = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).json()
        message = chat["choices"][0]["message"]
        assert message["content"] == "Answer: hi"
        assert message["reasoning_content"] == "Considering the request."
        assert chat["choices"][0]["finish_reason"] == "stop"
        assert chat["usage"]["total_tokens"] == 3

        tool_chat = client.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "What is the weather in Beijing?"}],
                "tools": tools,
            },
        ).json()
        assert tool_chat["choices"][0]["finish_reason"] == "tool_calls"
        call = tool_chat["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["name"] == "get_weather"
        assert json.loads(call["function"]["arguments"]) == {"city": "Beijing"}

        stream = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        ).text
        assert _chat_text(stream).strip() == "Answer: hi"
        assert '"reasoning_content": "Considering the request. "' in stream
        assert '"finish_reason": "stop"' in stream
        assert stream.rstrip().endswith("data: [DONE]")

        multi = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "n": 2},
        ).json()
        assert [choice["index"] for choice in multi["choices"]] == [0, 1]
        assert all(choice["message"]["content"] == "Answer: hi" for choice in multi["choices"])
        assert multi["usage"]["total_tokens"] == 6

        multi_stream = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "n": 2, "stream": True},
        ).text
        assert '"index": 1' in multi_stream
        assert multi_stream.rstrip().endswith("data: [DONE]")

        client.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "tools": tools,
                "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
                "response_format": {"type": "json_object"},
                "frequency_penalty": 0.5,
                "user": "u1",
            },
        )
        debug = client.get(f"{base}/debug/last").json()
        assert debug["extras"]["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}
        assert debug["extras"]["response_format"] == {"type": "json_object"}
        assert debug["extras"]["frequency_penalty"] == 0.5
        assert debug["extras"]["user"] == "u1"

        completions = client.post(
            f"{base}/v1/completions", json={"prompt": "hi", "echo": True}
        ).json()
        assert "Answer: hi" in completions["choices"][0]["text"]
        assert completions["choices"][0]["text"].startswith("hi")
        assert client.post(
            f"{base}/v1/completions", json={"prompt": "hi", "stream": True}
        ).text.rstrip().endswith("data: [DONE]")
        assert len(
            client.post(f"{base}/v1/completions", json={"prompt": ["a", "b"], "n": 2}).json()["choices"]
        ) == 4

        responses = client.post(
            f"{base}/v1/responses", json={"input": "hi", "instructions": "be brief"}
        ).json()
        assert [item["type"] for item in responses["output"]] == ["reasoning", "message"]
        assert responses["output_text"].strip() == "Answer: hi"
        tool_responses = client.post(
            f"{base}/v1/responses",
            json={
                "input": "What is the weather in Beijing?",
                "tools": [{"type": "function", "name": "get_weather", "parameters": {"type": "object"}}],
            },
        ).json()
        assert [item["type"] for item in tool_responses["output"]] == [
            "reasoning",
            "message",
            "function_call",
        ]
        response_stream = client.post(
            f"{base}/v1/responses",
            json={
                "input": "What is the weather in Beijing?",
                "tools": [{"type": "function", "name": "get_weather", "parameters": {"type": "object"}}],
                "stream": True,
            },
        ).text
        for event in (
            "response.created",
            "response.output_text.delta",
            "response.function_call_arguments.done",
            "response.completed",
        ):
            assert event in response_stream

        stored = client.get(f"{base}/v1/responses/{responses['id']}").json()
        assert stored["output_text"].strip() == "Answer: hi"
        assert client.delete(f"{base}/v1/responses/{responses['id']}").json()["deleted"]
        assert client.get(f"{base}/v1/responses/{responses['id']}").status_code == 404

        background = client.post(
            f"{base}/v1/responses", json={"input": "hi", "background": True}
        ).json()
        assert background["status"] == "in_progress"
        current = background
        for _ in range(100):
            current = client.get(f"{base}/v1/responses/{background['id']}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.02)
        assert current["status"] == "completed"
        assert current["output_text"].strip() == "Answer: hi"
        assert client.post(f"{base}/v1/responses/{background['id']}/cancel").status_code == 400
        assert client.delete(f"{base}/v1/responses/{background['id']}").json()["deleted"]

        encoded = base64.b64encode(b"file text").decode()
        file_response = client.post(
            f"{base}/v1/responses",
            json={
                "input": [{
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "input_file",
                        "file_data": encoded,
                        "filename": "a.txt",
                    }],
                }]
            },
        )
        assert file_response.status_code == 200
        debug = client.get(f"{base}/debug/last").json()
        assert any(
            isinstance(m["content"], str) and "file text" in m["content"]
            for m in debug["messages"]
        )

        embeddings = client.post(
            f"{base}/v1/embeddings", json={"input": ["a", "b"]}
        ).json()
        assert len(embeddings["data"][0]["embedding"]) == 8
        assert embeddings["data"][0]["embedding"] != embeddings["data"][1]["embedding"]
        encoded_embedding = client.post(
            f"{base}/v1/embeddings",
            json={"input": "a", "encoding_format": "base64"},
        ).json()["data"][0]["embedding"]
        assert len(base64.b64decode(encoded_embedding)) == 32

        moderation = client.post(
            f"{base}/v1/moderations", json={"input": ["ok", "violence"]}
        ).json()
        assert [item["flagged"] for item in moderation["results"]] == [False, True]


def test_code_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["code"]["base"]
    with httpx.Client(timeout=10.0) as client:
        chat = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "write a python function"}]},
        ).json()
        content = chat["choices"][0]["message"]["content"]
        assert content.startswith("```python")
        assert "def hello" in content
        completion = client.post(
            f"{base}/v1/completions", json={"prompt": "def add"}
        ).json()["choices"][0]["text"]
        assert "def add" in completion
        streamed = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "write python"}], "stream": True},
        ).text
        assert "def hello" in _chat_text(streamed)


def test_llm_anthropic_surface(serve_bundles) -> None:
    base = serve_bundles["servers"]["llm"]["base"]
    headers = {"anthropic-version": "2023-06-01"}
    cache = {"type": "ephemeral"}
    with httpx.Client(timeout=10.0) as client:
        listing = client.get(f"{base}/v1/models", headers=headers).json()
        assert listing["data"][0]["type"] == "model"
        assert client.get(f"{base}/v1/models/llm-fixture", headers=headers).json()["type"] == "model"
        assert client.get(f"{base}/v1/models/missing", headers=headers).status_code == 404

        message = client.post(
            f"{base}/v1/messages",
            json={
                "max_tokens": 32,
                "system": [{"type": "text", "text": "be brief", "cache_control": cache}],
                "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "any"},
                "thinking": {"type": "enabled", "budget_tokens": 16},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "What is the weather in Beijing?",
                                "cache_control": cache,
                            },
                            {
                                "type": "tool_result",
                                "tool_use_id": "t1",
                                "content": [
                                    {"type": "text", "text": "ok", "cache_control": cache},
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": "AAA",
                                        },
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
        )
        assert message.status_code == 200
        payload = message.json()
        assert [block["type"] for block in payload["content"]] == [
            "thinking",
            "text",
            "tool_use",
        ]
        assert payload["content"][2]["name"] == "get_weather"
        assert payload["stop_reason"] == "tool_use"

        debug = client.get(f"{base}/debug/last").json()
        assert isinstance(debug["messages"][0]["content"], list)
        assert debug["messages"][0]["content"][0]["cache_control"] == cache
        tool_message = next(m for m in debug["messages"] if m["role"] == "tool")
        assert isinstance(tool_message["content"], list)
        assert any(part.get("type") == "image_url" for part in tool_message["content"])
        assert any(part.get("cache_control") for part in tool_message["content"])
        assert debug["extras"]["tool_choice"] == "required"
        assert debug["extras"]["anthropic_thinking"]["budget_tokens"] == 16

        stream = client.post(
            f"{base}/v1/messages",
            json={
                "max_tokens": 16,
                "stream": True,
                "tools": [{"name": "get_weather", "input_schema": {"type": "object"}}],
                "messages": [{"role": "user", "content": "What is the weather in Beijing?"}],
            },
        ).text
        events = _anthropic_events(stream)
        for event in (
            "message_start",
            "content_block_start",
            "content_block_delta",
            "message_delta",
            "message_stop",
        ):
            assert event in events
        assert "thinking_delta" in stream
        assert "text_delta" in stream
        assert "input_json_delta" in stream

        count = client.post(
            f"{base}/v1/messages/count_tokens",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).json()
        assert count["input_tokens"] >= 1


def test_llm_realtime_host_state_machine(serve_bundles) -> None:
    websockets = pytest.importorskip("websockets")
    port = serve_bundles["servers"]["llm"]["port"]

    async def scenario() -> None:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/v1/realtime?model=llm-fixture"
        ) as ws:
            session = json.loads(await ws.recv())
            assert session["type"] == "session.created"

            await ws.send(json.dumps({"type": "session.update", "session": {"instructions": "be brief"}}))
            assert json.loads(await ws.recv())["type"] == "session.updated"

            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "hi"}],
                        },
                    }
                )
            )
            assert json.loads(await ws.recv())["type"] == "conversation.item.created"

            await ws.send(json.dumps({"type": "response.create"}))
            text = ""
            while True:
                event = json.loads(await ws.recv())
                if event["type"] == "response.output_text.delta":
                    text += event["delta"]
                if event["type"] == "response.done":
                    done = event
                    break
            assert text.strip() == "Answer: hi"
            assert done["response"]["status"] == "completed"

            await ws.send(json.dumps({"type": "response.cancel"}))
            assert json.loads(await ws.recv())["type"] == "error"

            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(b"abc").decode(),
                    }
                )
            )
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            assert json.loads(await ws.recv())["type"] == "input_audio_buffer.committed"
            audio_item = json.loads(await ws.recv())
            assert audio_item["item"]["content"][0]["transcript"] == "Hello from realtime audio."

            await ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
            assert json.loads(await ws.recv())["type"] == "input_audio_buffer.cleared"

    asyncio.run(scenario())


def test_asr_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["asr"]["base"]
    files = {"file": ("a.wav", b"audio", "audio/wav")}
    with httpx.Client(timeout=10.0) as client:
        assert client.post(
            f"{base}/v1/audio/transcriptions", files=files
        ).json()["text"] == "Hello, this is a speech test."
        assert client.post(
            f"{base}/v1/audio/transcriptions",
            files=files,
            data={"response_format": "text"},
        ).text == "Hello, this is a speech test."
        srt = client.post(
            f"{base}/v1/audio/transcriptions",
            files=files,
            data={"response_format": "srt"},
        ).text
        assert "00:00:00,000 --> 00:00:01,200" in srt
        assert "Hello, this is" in srt
        assert client.post(
            f"{base}/v1/audio/transcriptions",
            files=files,
            data={"response_format": "vtt"},
        ).text.startswith("WEBVTT")
        verbose = client.post(
            f"{base}/v1/audio/transcriptions",
            files=files,
            data={"response_format": "verbose_json"},
        ).json()
        assert verbose["task"] == "transcribe"
        assert verbose["language"] == "en"
        assert len(verbose["segments"]) == 2
        assert verbose["words"][0]["word"] == "Hello,"
        chinese = client.post(
            f"{base}/v1/audio/transcriptions",
            files={"file": ("zh.wav", b"audio", "audio/wav")},
        ).json()
        assert "你好" in chinese["text"]
        translated = client.post(
            f"{base}/v1/audio/translations",
            files=files,
            data={"response_format": "verbose_json"},
        ).json()
        assert translated["task"] == "translate"
        assert client.post(f"{base}/v1/audio/transcriptions", data={"model": "x"}).status_code == 400


def test_tts_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["tts"]["base"]
    with httpx.Client(timeout=10.0) as client:
        wav = client.post(
            f"{base}/v1/audio/speech",
            json={"input": "hi", "response_format": "wav"},
        )
        assert wav.status_code == 200
        assert wav.content.startswith(b"RIFF")
        assert b"WAVE" in wav.content[:16]
        assert b"data" in wav.content
        assert wav.headers["content-type"].startswith("audio/wav")
        mp3 = client.post(
            f"{base}/v1/audio/speech",
            json={"input": "hi", "response_format": "mp3"},
        )
        assert mp3.content.startswith(b"ID3")
        assert mp3.headers["content-type"].startswith("audio/mpeg")
        assert client.post(f"{base}/v1/audio/speech", json={}).status_code == 400


def test_audio_bundle_combined(serve_bundles) -> None:
    base = serve_bundles["servers"]["audio"]["base"]
    files = {"file": ("a.wav", b"audio", "audio/wav")}
    with httpx.Client(timeout=10.0) as client:
        assert client.post(
            f"{base}/v1/audio/transcriptions", files=files
        ).json()["text"] == "Hello, this is a speech test."
        wav = client.post(
            f"{base}/v1/audio/speech",
            json={"input": "hi", "response_format": "wav"},
        )
        assert wav.content.startswith(b"RIFF")


def test_image_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["image"]["base"]
    with httpx.Client(timeout=10.0) as client:
        generated = client.post(
            f"{base}/v1/images/generations",
            json={"prompt": "cat", "response_format": "url", "n": 2},
        ).json()
        assert len(generated["data"]) == 2
        assert generated["data"][0]["url"].startswith("data:image/png;base64,")
        assert generated["data"][0]["revised_prompt"] == "generate: cat"
        encoded = client.post(
            f"{base}/v1/images/generations",
            json={"prompt": "cat", "response_format": "b64_json"},
        ).json()["data"][0]["b64_json"]
        assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")
        edited = client.post(
            f"{base}/v1/images/edits",
            files={"image": ("i.png", b"img", "image/png")},
            data={"prompt": "cat"},
        ).json()
        assert edited["data"][0]["revised_prompt"] == "edit: cat"
        variation = client.post(
            f"{base}/v1/images/variations",
            files={"image": ("i.png", b"img", "image/png")},
        ).json()
        assert variation["data"][0]["revised_prompt"] == "variation: "
        assert client.post(f"{base}/v1/images/generations", json={}).status_code == 400


def test_video_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["video"]["base"]
    with httpx.Client(timeout=10.0) as client:
        created = client.post(
            f"{base}/v1/videos", json={"prompt": "a cat"}
        ).json()
        assert created["status"] == "queued"
        video_id = created["id"]
        first = client.get(f"{base}/v1/videos/{video_id}").json()
        assert first["status"] == "in_progress"
        second = client.get(f"{base}/v1/videos/{video_id}").json()
        assert second["status"] == "completed"
        assert client.get(f"{base}/v1/videos/{video_id}/content").content.startswith(b"\x00\x00\x00\x18ftyp")
        listing = client.get(f"{base}/v1/videos").json()
        assert listing["object"] == "list"
        assert any(item["id"] == video_id for item in listing["data"])
        assert client.delete(f"{base}/v1/videos/{video_id}").json()["deleted"] is True
        assert client.get(f"{base}/v1/videos/{video_id}").status_code == 404
        multipart = client.post(
            f"{base}/v1/videos",
            files={"input_reference": ("r.png", b"ref", "image/png")},
            data={"prompt": "a cat", "seconds": "4", "size": "1280x720"},
        )
        assert multipart.status_code == 200
        client.post(f"{base}/v1/videos", json={"prompt": "a second cat"})
        assert client.get(f"{base}/v1/videos", params={"limit": 1}).json()["has_more"] is True


def test_anthropic_only_bundle(serve_bundles) -> None:
    base = serve_bundles["servers"]["anthropic"]["base"]
    headers = {"anthropic-version": "2023-06-01"}
    with httpx.Client(timeout=10.0) as client:
        assert client.post(
            f"{base}/v1/messages",
            json={"max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
        ).status_code == 200
        assert client.post(
            f"{base}/v1/messages/count_tokens",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).json()["input_tokens"] >= 1
        assert client.get(f"{base}/v1/models", headers=headers).json()["data"][0]["type"] == "model"
        assert client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).status_code == 404
        assert client.post(f"{base}/v1/completions", json={"prompt": "hi"}).status_code == 404


def test_capability_gating_by_bundle(serve_bundles) -> None:
    chat = {"messages": [{"role": "user", "content": "hi"}]}
    with httpx.Client(timeout=10.0) as client:
        for kind in ("asr", "tts", "audio", "image", "video"):
            base = serve_bundles["servers"][kind]["base"]
            assert client.post(f"{base}/v1/chat/completions", json=chat).status_code == 404
            assert client.post(f"{base}/v1/messages", json=chat).status_code == 404
        code_base = serve_bundles["servers"]["code"]["base"]
        assert client.post(f"{code_base}/v1/messages", json=chat).status_code == 404


def test_legacy_bundle_gating(serve_bundles) -> None:
    base = serve_bundles["servers"]["legacy"]["base"]
    with httpx.Client(timeout=10.0) as client:
        assert client.get(f"{base}/health").status_code == 200
        assert client.get(f"{base}/v1/models").status_code == 200
        assert client.get(f"{base}/v1/models/llm-fixture").status_code == 200
        chat = client.post(
            f"{base}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).json()
        assert chat["choices"][0]["message"]["content"] == "Answer: hi"
        assert client.post(
            f"{base}/v1/messages",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ).status_code == 404
        assert client.post(f"{base}/v1/completions", json={"prompt": "hi"}).status_code == 404
        assert client.post(f"{base}/v1/embeddings", json={"input": "hi"}).status_code == 404
