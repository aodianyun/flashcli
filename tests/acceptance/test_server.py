"""Real ``flashserver`` daemon: start, load a bundle, call the API, unload.

Uses the built ``flashserver`` binary and a local native bundle; the daemon
spawns the real ``flashcli serve`` child. No HTTP handlers are stubbed.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request

from helpers import free_port, http_json, prepare_bundle, wait_json


def _start_server(flashserver_bin, flashcli_bin, cli_env, home, port):
    cfg = {
        "addr": f"127.0.0.1:{port}",
        "flashcli_bin": str(flashcli_bin),
        "log_dir": str(home / "home" / "logs" / "serve"),
        "max_loaded": 2,
    }
    cfg_path = home / "flashserver.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    env = dict(cli_env, FLASHCLI_SKIP_PREFLIGHT="1", FLASHCLI_BIN=str(flashcli_bin))
    proc = subprocess.Popen(
        [str(flashserver_bin), "--config", str(cfg_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_json(f"http://127.0.0.1:{port}/health", timeout=30)
    except Exception:
        proc.kill()
        out = proc.stdout.read() if proc.stdout else ""
        raise AssertionError(f"server did not start:\n{out}")
    return proc


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_server_load_native_bundle_over_http(flashserver_bin, flashcli_bin, cli_env, home):
    port = free_port()
    server = _start_server(flashserver_bin, flashcli_bin, cli_env, home, port)
    base = f"http://127.0.0.1:{port}"
    bundle = prepare_bundle("exec_echo_http", home)
    ref = str(bundle)
    try:
        status, health = http_json(f"{base}/health")
        assert status == 200 and health["status"] == "ok"

        status, version = http_json(f"{base}/v1/version")
        assert status == 200 and version["version"]

        status, loaded = http_json(f"{base}/v1/models/load", {"ref": ref})
        assert status == 200, loaded
        assert loaded["state"] == "ready"
        endpoint = loaded["endpoint"]
        assert endpoint.startswith("http://127.0.0.1:")

        # The child reports its own endpoint; the daemon must use it.
        with urllib.request.urlopen(endpoint + "/healthz", timeout=10) as resp:
            assert resp.status == 200

        status, current = http_json(f"{base}/v1/models/loaded")
        assert status == 200
        assert any(item["ref"] == ref for item in current["models"])

        status, logs = http_json(f"{base}/v1/logs?kind=model&ref={urllib.parse.quote(ref)}&lines=20")
        assert status == 200 and logs["kind"] == "model"
        assert logs["lines"], "per-model serve log was not captured"

        status, storage = http_json(f"{base}/v1/storage")
        assert status == 200 and storage["areas"]

        status, unloaded = http_json(f"{base}/v1/models/unload", {"ref": ref})
        assert status == 200 and unloaded["state"] == "unloaded"

        status, current = http_json(f"{base}/v1/models/loaded")
        assert status == 200 and current["models"] == []
    finally:
        _stop(server)


def test_server_rejects_run_only_bundle(flashserver_bin, flashcli_bin, cli_env, home):
    port = free_port()
    server = _start_server(flashserver_bin, flashcli_bin, cli_env, home, port)
    base = f"http://127.0.0.1:{port}"
    bundle = prepare_bundle("python_echo", home)
    try:
        status, body = http_json(f"{base}/v1/models/load", {"ref": str(bundle)})
        assert status >= 400
        assert "run-only" in json.dumps(body)
    finally:
        _stop(server)
