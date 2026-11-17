"""Real `flashcli app` against a local fake FlashHub (offline tier)."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import run_cli

MANIFEST_URL = "https://example.com/Demo-installer.exe"

MANIFEST = {
    "format": "flashcli-application",
    "app_format_version": 1,
    "protocol_version": 1,
    "name": "demo",
    "version": "1.0.0",
    "display_name": "Demo",
    "supported": {"os": ["linux", "darwin", "windows"], "arch": ["x86_64", "arm64"]},
    "install": {"commands": {"linux": MANIFEST_URL, "darwin": MANIFEST_URL, "windows": MANIFEST_URL}},
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


def _hub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _env(cli_env, hub, home):
    env = dict(cli_env)
    env["FLASHCLI_FLASHHUB_API"] = f"http://127.0.0.1:{hub.server_port}/api/v1/repos"
    env["FLASHCLI_HOME"] = str(home)
    return env


def test_app_list_show_and_dry_run(flashcli_bin, cli_env, tmp_path):
    hub = _hub()
    home = tmp_path / "home"
    env = _env(cli_env, hub, home)
    try:
        proc = run_cli(flashcli_bin, env, "app", "list", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "Demo" in proc.stdout

        proc = run_cli(flashcli_bin, env, "app", "show", "xym/demo", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "a/one:1" in proc.stdout and "1.0.0" in proc.stdout

        proc = run_cli(flashcli_bin, env, "app", "install", "xym/demo", "--dry-run", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "DRY RUN" in proc.stdout
        assert not (home / "flashserver" / "apps.json").exists()
    finally:
        hub.shutdown()


def test_app_install_url_and_uninstall(flashcli_bin, cli_env, tmp_path):
    hub = _hub()
    home = tmp_path / "home"
    env = _env(cli_env, hub, home)
    try:
        proc = run_cli(
            flashcli_bin, env, "app", "install", "xym/demo",
            "--no-model", "--no-start", timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Download page" in proc.stdout

        state_path = home / "flashserver" / "apps.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))["apps"]["xym/demo:1.0.0"]
        assert state["state"] == "ready"
        assert state["install"]["skipped"] is True

        proc = run_cli(flashcli_bin, env, "app", "status", "xym/demo", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert "ready" in proc.stdout

        proc = run_cli(flashcli_bin, env, "app", "uninstall", "xym/demo", "--yes", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert not json.loads(state_path.read_text(encoding="utf-8"))["apps"]
    finally:
        hub.shutdown()


def test_app_install_skips_shell_without_yes(flashcli_bin, cli_env, tmp_path):
    hub = _hub()
    home = tmp_path / "home"
    env = _env(cli_env, hub, home)
    # Swap the URL for a shell command to exercise the confirmation rule.
    global MANIFEST
    original = MANIFEST
    MANIFEST = json.loads(json.dumps(original))
    MANIFEST["install"]["commands"] = {"linux": "echo should-not-run", "darwin": "echo should-not-run", "windows": "echo should-not-run"}
    try:
        proc = run_cli(
            flashcli_bin, env, "app", "install", "xym/demo",
            "--no-model", "--no-start", timeout=180,
            # stdin is not a TTY here: the command must be skipped, not run.
        )
        assert proc.returncode == 0, proc.stderr
        assert "Install command declined." in proc.stdout
        # The plan prints the command, but it must not be executed.
        assert "$ echo should-not-run" not in proc.stdout
        state = json.loads((home / "flashserver" / "apps.json").read_text(encoding="utf-8"))["apps"]["xym/demo:1.0.0"]
        assert state["install"]["skipped"] is True
        assert not state["install"]["executed"]
    finally:
        MANIFEST = original
        hub.shutdown()


def test_app_install_confirms_shell_interactively(flashcli_bin, cli_env, tmp_path):
    hub = _hub()
    home = tmp_path / "home"
    env = _env(cli_env, hub, home)
    global MANIFEST
    original = MANIFEST
    MANIFEST = json.loads(json.dumps(original))
    MANIFEST["install"]["commands"] = {
        "linux": "echo confirmed-run",
        "darwin": "echo confirmed-run",
        "windows": "echo confirmed-run",
    }
    try:
        proc = run_cli(
            flashcli_bin, env, "app", "install", "xym/demo",
            "--no-model", "--no-start", timeout=180, input="y\n",
        )
        assert proc.returncode == 0, proc.stderr
        assert "Run this command? [y/N]" in proc.stdout
        # The command really ran (the echo output follows the "$ command" line).
        assert "$ echo confirmed-run" in proc.stdout
        assert "confirmed-run" in proc.stdout.split("$ echo confirmed-run", 1)[1]
        state = json.loads((home / "flashserver" / "apps.json").read_text(encoding="utf-8"))["apps"]["xym/demo:1.0.0"]
        assert state["install"]["executed"] is True
        assert not state["install"].get("skipped", False)
    finally:
        MANIFEST = original
        hub.shutdown()
