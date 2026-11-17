"""Real flashserver /v1/apps endpoints against a local fake FlashHub.

Also covers the prepare job: the bundle tree is synced from a fake repo so the
daemon exercises the real pull path without network.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import free_port, http_json, wait_json

BUNDLE = "a/one:1.0.0"
CELL = "sm89-cu124-linux-x86_64-py312"

BUNDLE_MANIFEST = {
    "format": "flashcli-model-bundle",
    "format_version": 4,
    "protocol_version": 1,
    "name": "one",
    "defaults": {
        "python_abi": "312",
        "entry": {"run": {"kind": "python", "module": "run", "attr": "RunEngine"}},
        "python_dependencies": {"pip": []},
    },
    "environments": {CELL: {"runtime": f"runtime/{CELL}"}},
}
RUN_PY = "class RunEngine:\n    def predict(self, **kw):\n        return {'echo': 'x'}\n"


def app_manifest(bundle: str) -> dict:
    return {
        "format": "flashcli-application",
        "app_format_version": 1,
        "protocol_version": 1,
        "name": "demo",
        "version": "1.0.0",
        "display_name": "Demo",
        "supported": {"os": ["linux", "darwin", "windows"], "arch": ["x86_64", "arm64"]},
        "install": {"commands": {"linux": "https://example.com/demo", "darwin": "https://example.com/demo", "windows": "https://example.com/demo"}},
        "model": {"bundles": [{"bundle": bundle, "default": True, "serve": {"options": {}}}]},
        "config": [],
    }


class _Hub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = None
        if self.path.startswith("/api/v1/apps?"):
            body = json.dumps(
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "id": 1,
                                "name": "demo",
                                "display_name": "Demo",
                                "domain": "通用Agent",
                                "version": "1.0.0",
                                "organization": {"name": "xym"},
                                "supported_os": ["linux"],
                                "supported_arch": ["x86_64"],
                                "model_bundles": [{"bundle": BUNDLE, "is_default": True}],
                            }
                        ],
                        "total": 1,
                        "page": 1,
                        "page_size": 20,
                    },
                }
            ).encode()
        elif self.path.startswith("/api/v1/apps/xym/demo"):
            body = json.dumps({"code": 0, "message": "success", "data": app_manifest(BUNDLE)}).encode()
        elif self.path.startswith("/api/v1/repos/a/one:1.0.0"):
            files = [
                {"download_url": f"http://127.0.0.1:{self.server.server_port}/repo/1/versions/1/flashcli-bundle.json",
                 "file_name": "flashcli-bundle.json", "file_size": 1, "md5_hash": ""},
                {"download_url": f"http://127.0.0.1:{self.server.server_port}/repo/1/versions/1/run.py",
                 "file_name": "run.py", "file_size": 1, "md5_hash": ""},
                {"download_url": f"http://127.0.0.1:{self.server.server_port}/repo/1/versions/1/checkpoint/model.bin",
                 "file_name": "model.bin", "file_size": 16, "md5_hash": ""},
            ]
            body = json.dumps({"code": 0, "data": {"files": files}}).encode()
        elif self.path == "/repo/1/versions/1/flashcli-bundle.json":
            body = json.dumps(BUNDLE_MANIFEST).encode()
        elif self.path == "/repo/1/versions/1/run.py":
            body = RUN_PY.encode()
        elif self.path == "/repo/1/versions/1/checkpoint/model.bin":
            body = b"0" * 16
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _HubServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Hub)


def _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub):
    port = free_port()
    cfg = tmp_path / "server.json"
    cfg.write_text(
        json.dumps(
            {
                "addr": f"127.0.0.1:{port}",
                "flashcli_bin": str(flashcli_bin),
                "log_dir": str(tmp_path / "logs"),
            }
        ),
        encoding="utf-8",
    )
    env = dict(cli_env)
    env["FLASHCLI_FLASHHUB_API"] = f"http://127.0.0.1:{hub.server_port}/api/v1/repos"
    env["FLASHCLI_HOME"] = str(tmp_path / "home")
    env["FLASHCLI_RUNTIME_ENV_KEY"] = CELL
    env["FLASHCLI_SKIP_CUDA_USERLAND"] = "1"
    env["FLASHCLI_SKIP_WEIGHTS"] = "1"
    proc = subprocess.Popen(
        [str(flashserver_bin), "--config", str(cfg)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, f"http://127.0.0.1:{port}"


def test_server_apps_list_and_manifest(flashserver_bin, flashcli_bin, cli_env, tmp_path):
    hub = _HubServer()
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    proc, base = _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub)
    try:
        wait_json(base + "/health", timeout=30)
        status, body = http_json(base + "/v1/apps?page=1")
        assert status == 200, body
        assert body["apps"][0]["display_name"] == "Demo"
        status, body = http_json(base + "/v1/apps/xym/demo")
        assert status == 200, body
        assert body["manifest"]["name"] == "demo"
        assert body["org"] == "xym"
        status, _ = http_json(base + "/v1/apps/xym/demo/status")
        assert status == 404
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        hub.shutdown()


def test_server_app_prepare_pulls_bundle(flashserver_bin, flashcli_bin, cli_env, tmp_path):
    hub = _HubServer()
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    proc, base = _start_daemon(flashserver_bin, flashcli_bin, cli_env, tmp_path, hub)
    try:
        wait_json(base + "/health", timeout=30)
        status, body = http_json(base + "/v1/apps/xym/demo/prepare", {"version": "1.0.0"})
        assert status == 202, body
        job_id = body["job_id"]
        deadline = time.time() + 60
        state = ""
        while time.time() < deadline:
            _, job = http_json(f"{base}/v1/jobs/{job_id}")
            state = job.get("state", "")
            if state in ("done", "failed"):
                break
            time.sleep(0.2)
        assert state == "done", job.get("error") or job

        status, st = http_json(base + "/v1/apps/xym/demo/status?version=1.0.0")
        assert status == 200, st
        assert st["models"][0]["prepared"] is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        hub.shutdown()
