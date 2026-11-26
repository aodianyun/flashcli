"""Real flashserver gateway E2E with a local FlashHub fixture.

The bundle is a real Python ``ServeEngine`` (the same fixtures used by the
protocol acceptance tier), pulled through the real FlashHub sync path, prepared
into a bundle venv, started by the scheduler, and called through ``/v1``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from helpers import free_port, http_json, wait_json

pytestmark = pytest.mark.skipif(
    os.environ.get("FLASHCLI_ACCEPTANCE_HEAVY") != "1",
    reason="heavy tier: creates a bundle venv; set FLASHCLI_ACCEPTANCE_HEAVY=1",
)

CELL = "sm89-cu124-linux-x86_64-py312"
REF = "a/echo:1.0.0"
NAME = "echo"
VERSION = "1.0.0"

BUNDLE_MANIFEST = {
    "format": "flashcli-model-bundle",
    "format_version": 4,
    "protocol_version": 1,
    "name": NAME,
    "description": "Gateway E2E fixture: deterministic ServeEngine echo.",
    "serve_options": [
        {"name": "warmup", "type": "string", "help": "Warmup spec.", "phase": "warmup"}
    ],
    "defaults": {
        "python_abi": "312",
        "entry": {
            "serve": {
                "kind": "python",
                "module": "serve",
                "attr": "ServeEngine",
                "mode": "engine",
                "capabilities": [
                    "openai.chat",
                    "openai.embeddings",
                    "openai.moderations",
                    "openai.audio.transcriptions",
                    "anthropic.messages",
                    "anthropic.count_tokens",
                ],
            }
        },
        "python_dependencies": {"torch": False, "pip": []},
        "serve_options": [
            {"name": "warmup", "type": "string", "help": "Warmup spec.", "phase": "warmup"}
        ],
    },
    "environments": {CELL: {"runtime": "runtime/test"}},
}

SERVE_PY = "from serve_fixture_engines import LLMEngine as ServeEngine\n"


def _manifest(base: str) -> dict:
    return copy.deepcopy(BUNDLE_MANIFEST)


class _Hub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        base = f"http://127.0.0.1:{self.server.server_port}"
        files = [
            ("flashcli-bundle.json", 1),
            ("serve.py", 1),
            ("serve_fixture_engines.py", 1),
            ("checkpoint/model.safetensors", 1),
            ("runtime/test/.keep", 1),
        ]
        if self.path == f"/api/v1/repos/a/{NAME}:{VERSION}":
            body = json.dumps(
                {
                    "code": 0,
                    "data": {
                        "files": [
                            {
                                "download_url": f"{base}/repo/1/versions/1/{name}",
                                "file_name": name.rsplit("/", 1)[-1],
                                "file_size": size,
                                "md5_hash": "",
                            }
                            for name, size in files
                        ]
                    },
                }
            ).encode()
        elif self.path == "/repo/1/versions/1/flashcli-bundle.json":
            body = json.dumps(_manifest(base)).encode()
        elif self.path == "/repo/1/versions/1/serve.py":
            body = SERVE_PY.encode()
        elif self.path == "/repo/1/versions/1/serve_fixture_engines.py":
            path = os.path.join(os.path.dirname(__file__), "serve_fixture_engines.py")
            body = open(path, "rb").read()
        elif self.path == "/repo/1/versions/1/checkpoint/model.safetensors":
            body = b""
        elif self.path == "/repo/1/versions/1/runtime/test/.keep":
            body = b""
        elif self.path == "/weights/model.safetensors":
            body = b""
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _HubServer(ThreadingHTTPServer):
    pass


def _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub_port):
    port = free_port()
    cfg = tmp_path / "server.json"
    cfg.write_text(
        json.dumps(
            {
                "addr": f"127.0.0.1:{port}",
                "flashcli_bin": str(flashcli_bin),
                "log_dir": str(tmp_path / "logs"),
                "resident_start_wait_seconds": 120,
            }
        ),
        encoding="utf-8",
    )
    env = dict(cli_env)
    env["FLASHCLI_FLASHHUB_API"] = f"http://127.0.0.1:{hub_port}/api/v1/repos"
    env["FLASHCLI_HOME"] = str(tmp_path / "home")
    env["FLASHCLI_RUNTIME_ENV_KEY"] = CELL
    env["FLASHCLI_SKIP_CUDA_USERLAND"] = "1"
    proc = subprocess.Popen(
        [str(flashserver_bin), "--config", str(cfg)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, f"http://127.0.0.1:{port}"


def _http_json_headers(url: str, payload: dict, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _http_multipart(url: str, fields: dict, file_field: str, filename: str, content: bytes) -> tuple[int, dict]:
    boundary = "----flashcli-gateway-e2e"
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
        + content
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url,
        data=b"".join(chunks),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _http_text(url: str, payload: dict) -> str:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode()


def _wait_job(base, job_id, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, job = http_json(f"{base}/api/v1/jobs/{job_id}")
        if job["state"] in ("done", "failed"):
            assert job["state"] == "done", job.get("error") or job
            return
        time.sleep(0.3)
    raise AssertionError(f"job {job_id} did not finish")


def test_gateway_real_bundle(flashserver_bin, flashcli_bin, cli_env, tmp_path):
    hub = _HubServer(("127.0.0.1", 0), _Hub)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    proc, base = _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub.server_port)
    try:
        wait_json(base + "/health", timeout=30)

        status, body = http_json(base + "/api/v1/models/preload", {"ref": REF})
        assert status in (200, 202), body
        if job_id := body.get("job_id"):
            _wait_job(base, job_id)

        deadline = time.time() + 120
        while time.time() < deadline:
            _, models = http_json(base + "/api/v1/models")
            model = next((m for m in models["models"] if m["ref"] == REF), None)
            if model and model.get("preload") == "preloaded":
                break
            time.sleep(0.3)
        else:
            raise AssertionError(f"model did not preload: {models}")

        # The fixture ships its checkpoint inline; record the shared-store marker
        # that a real downloaded bundle would already have so restart readiness
        # can be checked without a weights.repo.
        digest = hashlib.sha256(b"huggingface\x00echo\x00main").hexdigest()[:8]
        weights_key = model.get("weights_key") or f"store/huggingface/{NAME}@main-{digest}"
        if weights_key:
            weights_root = tmp_path / "home" / "models" / weights_key
            checkpoint = weights_root / "checkpoint"
            checkpoint.mkdir(parents=True, exist_ok=True)
            (weights_root / "model.safetensors").write_bytes(b"")
            (checkpoint / "model.safetensors").write_bytes(b"")
            (weights_root / ".flashcli_model.json").write_text(
                json.dumps({"preset": NAME, "checkpoint": str(checkpoint)}),
                encoding="utf-8",
            )

        # Prepared disk state survives a daemon restart; the next request starts
        # a fresh resident child.
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc, base = _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub.server_port)
        wait_json(base + "/health", timeout=30)
        _, models = http_json(base + "/api/v1/models")
        model = next((m for m in models["models"] if m["ref"] == REF), None)
        assert model and model.get("preload") == "preloaded", models

        # Inference goes through the gateway; the scheduler starts the real
        # bundle child and the response model is rewritten to the full ref.
        status, reply = http_json(
            base + "/v1/chat/completions",
            {
                "model": REF,
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 16,
            },
        )
        assert status == 200, reply
        assert reply["model"] == REF
        assert reply["choices"][0]["message"]["content"] == "Answer: hello"

        # SSE goes through the same lease and rewrites the model on every event.
        stream = _http_text(
            base + "/v1/chat/completions",
            {
                "model": REF,
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 16,
                "stream": True,
            },
        )
        assert "data: " in stream and "Answer:" in stream and "hello" in stream and REF in stream

        # Other host-owned routes go through the same bundle and gateway.
        status, embeddings = http_json(
            base + "/v1/embeddings", {"model": REF, "input": "hello"}
        )
        assert status == 200 and embeddings["data"][0]["embedding"]

        status, moderation = http_json(
            base + "/v1/moderations", {"model": REF, "input": "violence"}
        )
        assert status == 200 and moderation["results"][0]["flagged"] is True

        anthropic = {"anthropic-version": "2023-06-01"}
        status, message = _http_json_headers(
            base + "/v1/messages",
            {
                "model": REF,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hello"}],
            },
            anthropic,
        )
        assert status == 200 and message["content"]

        status, count = _http_json_headers(
            base + "/v1/messages/count_tokens",
            {"model": REF, "messages": [{"role": "user", "content": "hello"}]},
            anthropic,
        )
        assert status == 200 and count["input_tokens"] >= 1

        status, audio = _http_multipart(
            base + "/v1/audio/transcriptions",
            {"model": REF},
            "file",
            "hello.wav",
            b"RIFF....WAVE",
        )
        assert status == 200 and "Hello from realtime audio." in audio["text"]

        # A resident model is busy for disk removal; force stops it first.
        status, body = http_json(base + "/api/v1/models/unload", {"ref": REF})
        assert status == 409, body
        assert body["error"]["code"] == "model_busy", body
        status, body = http_json(base + "/api/v1/models/unload", {"ref": REF, "force": True})
        assert status == 200, body
        assert body["preload"] == "absent"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        hub.shutdown()
