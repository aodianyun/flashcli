"""Offline end-to-end sync of a FlashHub repo through the real CLI.

Serves a local index with the *new* CDN layout (``<path>/<name>/<name>``) and the
old one, then runs ``flashcli pull`` against it. Asserts the files land at the
paths declared by the manifest (this is the regression that shipped in 1.0.7).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import CELL, PY_ABI, run_cli

MANIFEST = {
    "format": "flashcli-model-bundle",
    "format_version": 4,
    "protocol_version": 1,
    "name": "sync_demo",
    "defaults": {
        "python_abi": PY_ABI,
        "entry": {"run": {"kind": "python", "module": "run", "attr": "RunEngine"}},
        "python_dependencies": {"pip": []},
    },
    "environments": {CELL: {"runtime": f"runtime/{CELL}"}},
}

RUN_PY = "class RunEngine:\n    def predict(self, **kw):\n        return {'echo': 'x'}\n"
EXTRA_PY = "VALUE = 1\n"
NOTICE = "ok\n"


class _Handler(BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}

    def do_GET(self):  # noqa: N802
        body = self.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_pull_syncs_new_cdn_layout(flashcli_bin, cli_env, tmp_path):
    state: dict[str, object] = {}

    class Handler(_Handler):
        files = {}

        def do_GET(self):  # noqa: N802
            if self.path == "/api/v1/repos/demo/sync_demo:1.0.0":
                index = state["index"]
                body = json.dumps(index).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        files = {
            "/repo/1/versions/2/flashcli-bundle.json/flashcli-bundle.json": json.dumps(MANIFEST).encode(),
            "/repo/1/versions/2/run.py/run.py": RUN_PY.encode(),
            "/repo/1/versions/2/sub/x.py/x.py": EXTRA_PY.encode(),
            "/repo/1/versions/2/NOTICE": NOTICE.encode(),
        }
        Handler.files = files
        state["index"] = {
            "code": 0,
            "data": {
                "files": [
                    {"download_url": f"{base}/repo/1/versions/2/flashcli-bundle.json/flashcli-bundle.json",
                     "file_name": "flashcli-bundle.json", "file_size": len(files["/repo/1/versions/2/flashcli-bundle.json/flashcli-bundle.json"]), "md5_hash": ""},
                    {"download_url": f"{base}/repo/1/versions/2/run.py/run.py",
                     "file_name": "run.py", "file_size": len(RUN_PY), "md5_hash": ""},
                    {"download_url": f"{base}/repo/1/versions/2/sub/x.py/x.py",
                     "file_name": "x.py", "file_size": len(EXTRA_PY), "md5_hash": ""},
                    {"download_url": f"{base}/repo/1/versions/2/NOTICE",
                     "file_name": "NOTICE", "file_size": len(NOTICE), "md5_hash": ""},
                ]
            },
        }

        env = dict(cli_env)
        env["FLASHCLI_FLASHHUB_API"] = f"{base}/api/v1/repos"
        env["FLASHCLI_HOME"] = str(tmp_path / "home")
        proc = run_cli(flashcli_bin, env, "pull", "demo/sync_demo:1.0.0", timeout=300)

        root = tmp_path / "home" / "bundles"
        manifest = next(root.rglob("flashcli-bundle.json"), None)
        assert manifest is not None, (proc.stdout + proc.stderr)[-4000:]
        base_dir = manifest.parent

        assert (base_dir / "run.py").is_file()
        assert (base_dir / "sub" / "x.py").is_file()
        assert (base_dir / "NOTICE").is_file()
        # The 1.0.7 bug: file names were created as directories.
        assert not (base_dir / "run.py").is_dir()
        assert not (base_dir / "sub" / "x.py").is_dir()
    finally:
        server.shutdown()
