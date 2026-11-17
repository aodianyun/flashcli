"""Real flashserver /v1/apps endpoints against a local fake FlashHub."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import free_port, http_json, wait_json

MANIFEST = {
    "format": "flashcli-application",
    "app_format_version": 1,
    "protocol_version": 1,
    "name": "demo",
    "version": "1.0.0",
    "display_name": "Demo",
    "supported": {"os": ["linux", "darwin", "windows"], "arch": ["x86_64", "arm64"]},
    "install": {"commands": {"linux": "https://example.com/demo", "darwin": "https://example.com/demo", "windows": "https://example.com/demo"}},
    "model": {"bundles": [{"bundle": "a/one:1", "default": True, "serve": {"options": {}}}]},
    "config": [],
}

LIST = {
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
                "model_bundles": [{"bundle": "a/one:1", "is_default": True}],
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
    },
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/v1/apps?"):
            body = json.dumps(LIST).encode()
        elif self.path == "/api/v1/apps/xym/demo":
            body = json.dumps({"code": 0, "message": "success", "data": MANIFEST}).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_server_apps_endpoints(flashserver_bin, flashcli_bin, cli_env, home, tmp_path):
    hub = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
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
    env["FLASHCLI_HOME"] = str(home / "server-home")
    proc = subprocess.Popen(
        [str(flashserver_bin), "--config", str(cfg)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
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
