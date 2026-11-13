"""Shared helpers for the acceptance tier (imported as ``helpers``)."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "conformance" / "fixtures"
CELL = "sm89-cu124-linux-x86_64-py312"
PY_ABI = "312"


def prepare_bundle(name: str, home: Path) -> Path:
    """Copy a conformance fixture to a stable path and align it with py312."""
    dest = home / "bundles" / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(FIXTURES / name, dest)
    manifest = dest / "flashcli-bundle.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("format_version", 3) >= 4:
        data.setdefault("defaults", {})["python_abi"] = PY_ABI
        data["environments"] = {CELL: {"runtime": f"runtime/{CELL}"}}
    else:
        data["python_abi"] = PY_ABI
        data["runtime"] = {CELL: f"runtime/{CELL}"}
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # Make the bundle complete enough for `bundle validate`: the declared runtime
    # directory exists and weights are present locally.
    (dest / "runtime" / CELL).mkdir(parents=True, exist_ok=True)
    checkpoint = dest / "checkpoint"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "model.bin").write_bytes(b"\0" * 16)
    return dest


def run_cli(binary: Path, env: dict[str, str], *args: str, timeout: int = 600):
    return subprocess.run([str(binary), *args], env=env, capture_output=True, text=True, timeout=timeout)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_json(url: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(0.2)
    raise AssertionError(f"{url} did not become ready: {last}")


def http_json(url: str, payload: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else {}
