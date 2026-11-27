#!/usr/bin/env python3
"""Real-GPU flashserver scheduler acceptance.

This is an opt-in, reproducible check of the behaviours that cannot be covered
with fake launchers: real VRAM accounting, two public models on one GPU, LRU
eviction, queue timeout, child crash, idle stop, busy unload, and daemon restart.

It needs:
  * Linux/WSL with an NVIDIA GPU visible to nvidia-smi
  * ``dist/go/flashserver-linux-amd64`` and ``dist/go/flashcli-linux-amd64``
    (``bash scripts/build_dev_bins.sh``)
  * network access to FlashHub/ModelScope the first time, and ~10 GiB free disk
  * a CUDA-capable bundle venv; the script discovers the venv ``nvidia/*/lib``
    directories and exports them through ``LD_LIBRARY_PATH``.

Run it from the repository root:

  bash scripts/build_dev_bins.sh
  python3 scripts/verify_scheduler_public.py

Model refs, the home directory, and the runtime cell are environment-overridable:

  FLASHCLI_SCHEDULER_MODEL_A   default xym/hunyuan_05b_instruct_rtx:1.0.0
  FLASHCLI_SCHEDULER_MODEL_B   default xym/ernie45_0p3b_rtx:1.0.0
  FLASHCLI_SCHEDULER_HOME      default ~/.flashcli/scheduler-acceptance
  FLASHCLI_SCHEDULER_PORT      default 8795 (set another port if it is reserved)
  FLASHCLI_RUNTIME_ENV_KEY     default sm89-cu130-linux-x86_64-py312
  FLASHSERVER_BIN / FLASHCLI_BIN
  FLASHCLI_BUNDLE_PIP_SPEC     default the installed local protocol, else the repo

The home directory is kept so repeated runs reuse downloaded weights and venvs.
Use FLASHCLI_SCHEDULER_FRESH=1 to start from an empty home.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_BIN = Path(os.environ.get("FLASHSERVER_BIN", ROOT / "dist" / "go" / "flashserver-linux-amd64"))
CLI_BIN = Path(os.environ.get("FLASHCLI_BIN", ROOT / "dist" / "go" / "flashcli-linux-amd64"))
HOME = Path(
    os.environ.get(
        "FLASHCLI_SCHEDULER_HOME",
        Path.home() / ".flashcli" / "scheduler-acceptance",
    )
)
BASE = f"http://127.0.0.1:{int(os.environ.get('FLASHCLI_SCHEDULER_PORT', '8795'))}"
MODEL_A = os.environ.get("FLASHCLI_SCHEDULER_MODEL_A", "xym/hunyuan_05b_instruct_rtx:1.0.0")
MODEL_B = os.environ.get("FLASHCLI_SCHEDULER_MODEL_B", "xym/ernie45_0p3b_rtx:1.0.0")
RUNTIME_CELL = os.environ.get("FLASHCLI_RUNTIME_ENV_KEY", "sm89-cu130-linux-x86_64-py312")
HOG_MIB = int(os.environ.get("FLASHCLI_SCHEDULER_HOG_MIB", "4000"))


def log(*args):
    print(*args, flush=True)


def skip(reason: str) -> int:
    log(f"SKIP: {reason}")
    return 0


def mirror_env() -> dict[str, str]:
    env = dict(os.environ)
    mirror = Path(os.environ.get("HOME", "~")).expanduser() / ".flashcli" / "mirror.env"
    if mirror.is_file():
        for line in mirror.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip())
    return env


def daemon_env(extra_ld: str = "") -> dict[str, str]:
    env = mirror_env()
    env["FLASHCLI_HOME"] = str(HOME)
    env.setdefault("FLASHCLI_RUNTIME_ENV_KEY", RUNTIME_CELL)
    env.setdefault("FLASHCLI_SKIP_CUDA_USERLAND", "1")
    if "FLASHCLI_BUNDLE_PIP_SPEC" not in env:
        installed = Path("/usr/local/share/flashcli/flashcli-bundle")
        env["FLASHCLI_BUNDLE_PIP_SPEC"] = (
            f"{installed}[infer]" if installed.is_dir() else f"{ROOT / 'flashcli-bundle'}[infer]"
        )
    if extra_ld:
        env["LD_LIBRARY_PATH"] = extra_ld + ":" + env.get("LD_LIBRARY_PATH", "")
    return env


def start_daemon(name: str, cfg: dict, env: dict[str, str]) -> subprocess.Popen:
    cfg_path = HOME / f"{name}.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log_file = open(HOME / f"{name}.log", "ab")
    proc = subprocess.Popen(
        [str(SERVER_BIN), "--config", str(cfg_path)],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            req("GET", "/health", timeout=2)
            return proc
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("daemon health timeout")


def cleanup_children() -> None:
    """Kill serve children left behind by a previous interrupted run.

    The check is scoped to this acceptance HOME so a real installed service is
    never touched.
    """
    marker = f"FLASHCLI_HOME={HOME}".encode()
    for proc_dir in glob.glob("/proc/[0-9]*"):
        try:
            env = Path(proc_dir, "environ").read_bytes().split(b"\0")
            if marker not in env:
                continue
            cmd = Path(proc_dir, "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if "flashcli_bundle.infer serve" not in cmd and "flashcli-linux-amd64 serve" not in cmd:
                continue
            os.kill(int(Path(proc_dir).name), signal.SIGKILL)
            log("cleanup: killed leftover child", Path(proc_dir).name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue


def stop_daemon(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    cleanup_children()


def req(method: str, path: str, payload: dict | None = None, timeout: int = 600):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_job(job_id: str, timeout: int = 1800) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        _, job = req("GET", f"/api/v1/jobs/{job_id}", timeout=30)
        state = job.get("state")
        if state != last:
            log("  job", job_id, state)
            last = state
        if state == "done":
            return
        if state == "failed":
            raise RuntimeError(job)
        time.sleep(1)
    raise RuntimeError(f"job {job_id} timeout")


def wait_preload(ref: str, timeout: int = 1800) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body = req("GET", "/api/v1/models", timeout=30)
        model = next((m for m in body["models"] if m["ref"] == ref), None)
        if model and model.get("preload") == "preloaded":
            return model
        time.sleep(1)
    raise RuntimeError(f"{ref} did not preload")


def preload(ref: str) -> dict:
    status, body = req("POST", "/api/v1/models/preload", {"ref": ref}, timeout=120)
    assert status in (200, 202), body
    if body.get("job_id"):
        wait_job(body["job_id"])
    return wait_preload(ref)


def reservations() -> dict[str, dict]:
    _, body = req("GET", "/api/v1/scheduler", timeout=30)
    return {item["ref"]: item for item in body["reservations"]}


def chat(ref: str, prompt: str = "Say hi.", max_tokens: int = 128, timeout: int = 600):
    return req(
        "POST",
        "/v1/chat/completions",
        {
            "model": ref,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        },
        timeout=timeout,
    )


def assert_chat(ref: str) -> str:
    status, reply = chat(ref)
    assert status == 200, reply
    message = reply["choices"][0]["message"]
    text = message.get("content") or message.get("reasoning_content") or ""
    assert text.strip(), reply
    return text


def wait_chat(ref: str, timeout: int = 20) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, reply = chat(ref)
        if status == 200:
            message = reply["choices"][0]["message"]
            text = message.get("content") or message.get("reasoning_content") or ""
            if text.strip():
                return text
        last = (status, reply)
        time.sleep(1)
    raise AssertionError(last)


def stream_in_thread(ref: str, max_tokens: int = 1024, delay: float = 0.005) -> dict:
    box = {"started": threading.Event(), "done": threading.Event(), "error": None, "bytes": 0}

    def run():
        try:
            payload = {
                "model": ref,
                "messages": [{"role": "user", "content": "Count from 1 to 1000, separated by commas."}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": True,
            }
            request = urllib.request.Request(
                BASE + "/v1/chat/completions",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                while True:
                    chunk = response.read(256)
                    if not chunk:
                        break
                    box["bytes"] += len(chunk)
                    box["started"].set()
                    # Slow consumer keeps the gateway lease open long enough to
                    # exercise queueing and busy unload deterministically.
                    time.sleep(delay)
        except Exception as exc:  # a forced unload cuts the stream
            box["error"] = repr(exc)
        finally:
            box["done"].set()

    threading.Thread(target=run, daemon=True).start()
    return box


def wait_active(ref: str, minimum: int = 1, timeout: int = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = reservations().get(ref)
        if item and item.get("active_requests", 0) >= minimum:
            return item
        time.sleep(0.2)
    raise RuntimeError(f"{ref} never reached {minimum} active requests: {reservations()}")


def wait_state(ref: str, state: str, timeout: int = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = reservations().get(ref)
        if item and item.get("state") == state:
            return item
        time.sleep(0.2)
    raise RuntimeError(f"{ref} never reached {state}: {reservations()}")


def chat_in_thread(ref: str, max_tokens: int = 32) -> dict:
    box = {"done": threading.Event(), "status": None, "reply": None, "error": None}

    def run():
        try:
            box["status"], box["reply"] = chat(ref, max_tokens=max_tokens, timeout=600)
        except Exception as exc:
            box["error"] = repr(exc)
        finally:
            box["done"].set()

    threading.Thread(target=run, daemon=True).start()
    return box


def wait_no_resident(timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not reservations():
            return
        time.sleep(0.3)
    raise RuntimeError(f"residents did not stop: {reservations()}")


def lib_paths() -> str:
    paths: list[str] = []
    for pattern in ("nvidia/*/lib", "nvidia/*/lib64"):
        paths.extend(glob.glob(str(HOME / "runtimes" / "*" / "venv" / "lib" / "python3.12" / "site-packages" / pattern)))
    ordered = sorted(dict.fromkeys(paths))
    return ":".join(ordered)


def common_config() -> dict:
    return {
        "addr": f"127.0.0.1:{int(os.environ.get('FLASHCLI_SCHEDULER_PORT', '8795'))}",
        "flashcli_bin": str(CLI_BIN),
        "log_dir": str(HOME / "logs" / "serve"),
        "resident_start_wait_seconds": 600,
        "queue_timeout_seconds": 3,
        "queue_max": 16,
        "auto_pull": True,
        "public_host": "127.0.0.1",
    }


def main() -> int:
    if shutil.which("nvidia-smi") is None:
        return skip("nvidia-smi not found")
    if not SERVER_BIN.is_file() or not CLI_BIN.is_file():
        return skip("dist/go binaries not found (run scripts/build_dev_bins.sh)")
    if os.environ.get("FLASHCLI_SCHEDULER_FRESH") == "1":
        shutil.rmtree(HOME, ignore_errors=True)
    HOME.mkdir(parents=True, exist_ok=True)
    cleanup_children()

    log("== preload public models ==")
    proc = start_daemon("preload", {**common_config(), "idle_stop_seconds": 600}, daemon_env())
    try:
        preload(MODEL_A)
        preload(MODEL_B)
    finally:
        stop_daemon(proc)

    ld = lib_paths()
    assert ld, "no CUDA userland libs in bundle venvs"
    log("LD_LIBRARY_PATH entries:", ld)

    log("== A: max_loaded=0, low VRAM, two residents, child crash ==")
    proc = start_daemon("max0", {**common_config(), "idle_stop_seconds": 600}, daemon_env(ld))
    try:
        _, sched = req("GET", "/api/v1/scheduler")
        assert sched["slots"]["max"] == 0, sched["slots"]
        assert sched["vram_headroom_mib"] == 512, sched["vram_headroom_mib"]
        log("defaults", sched["slots"], sched["vram_headroom_mib"])

        venv_python = glob.glob(str(HOME / "runtimes" / "*" / "venv" / "bin" / "python"))
        if venv_python:
            log("low-VRAM admission with a", HOG_MIB, "MiB hog")
            hog = subprocess.Popen(
                [
                    venv_python[0],
                    "-c",
                    f"import torch,time; x=torch.empty({HOG_MIB}*1024*1024, dtype=torch.uint8, device='cuda'); "
                    "x.fill_(1); print('HOG', flush=True); time.sleep(120)",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                log("vram hog", hog.stdout.readline().strip())
                status, body = req(
                    "POST",
                    "/v1/chat/completions",
                    {
                        "model": MODEL_A,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 16,
                    },
                    timeout=120,
                )
                assert status == 503, (status, body)
                code = body.get("error", {}).get("code")
                assert code in ("no_placement", "queue_full"), body
                log("low VRAM rejected", status, code)
            finally:
                hog.kill()
                hog.wait(timeout=10)
            time.sleep(2)
            log("VRAM released, chat:", wait_chat(MODEL_A)[:60])
        else:
            log("SKIP low-VRAM hog: no bundle venv python")

        log("chat B:", assert_chat(MODEL_B)[:60])
        current = reservations()
        assert set(current) == {MODEL_A, MODEL_B}, current
        assert all(item["state"] in ("ready", "busy") for item in current.values()), current
        log("both resident", {key: value["state"] for key, value in current.items()})

        _, resources = req("GET", "/api/v1/resources")
        loaded = next(item for item in resources["loaded"] if item["ref"] == MODEL_B)
        old_pid = loaded["pid"]
        os.kill(old_pid, signal.SIGKILL)
        time.sleep(0.5)
        log("killed child", old_pid, "restart chat:", assert_chat(MODEL_B)[:60])
        _, resources = req("GET", "/api/v1/resources")
        new_pid = next(item for item in resources["loaded"] if item["ref"] == MODEL_B)["pid"]
        assert new_pid != old_pid, (old_pid, new_pid)
        assert len(resources["loaded"]) == 2, resources["loaded"]
        log("crash restart pid", old_pid, "->", new_pid)
    finally:
        stop_daemon(proc)

    log("== A2: idle stop keeps preload and restarts on demand ==")
    proc = start_daemon("idle", {**common_config(), "idle_stop_seconds": 6}, daemon_env(ld))
    try:
        log("chat A:", assert_chat(MODEL_A)[:60])
        wait_no_resident(timeout=30)
        _, models = req("GET", "/api/v1/models")
        model = next(m for m in models["models"] if m["ref"] == MODEL_A)
        assert model["preload"] == "preloaded" and model["resident"] == "stopped", model
        log("idle stop kept preload")
        log("restart after idle stop:", assert_chat(MODEL_A)[:60])
    finally:
        stop_daemon(proc)

    log("== B: max_loaded=1, queue timeout, LRU eviction, restart with active stream ==")
    max1_cfg = {**common_config(), "max_loaded": 1, "idle_stop_seconds": 30, "queue_timeout_seconds": 5}
    proc = start_daemon("max1", max1_cfg, daemon_env(ld))
    try:
        # Start A and issue B while A is still starting: max_loaded=1 must queue
        # B and time out, without relying on how long a generated stream runs.
        box = chat_in_thread(MODEL_A, max_tokens=64)
        wait_state(MODEL_A, "starting")
        started = time.time()
        status, body = req(
            "POST",
            "/v1/chat/completions",
            {"model": MODEL_B, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16},
            timeout=120,
        )
        elapsed = time.time() - started
        assert status == 503, (status, body)
        assert body.get("error", {}).get("code") in ("no_placement", "queue_full"), body
        assert elapsed >= 4.0, elapsed
        log("queued B rejected after", round(elapsed, 2), "s", body["error"]["code"])
        assert box["done"].wait(120), "model A request did not finish"
        assert box["status"] == 200, box
        time.sleep(1)

        log("after release, B should evict idle A")
        assert_chat(MODEL_B)
        current = reservations()
        assert MODEL_B in current, current
        assert MODEL_A not in current, current
        log("LRU eviction", {key: value["state"] for key, value in current.items()})

        # Restart the daemon while a stream is active. The in-flight client is
        # cut, the resident is gone after restart, and the disk preload remains.
        box = stream_in_thread(MODEL_B)
        assert box["started"].wait(120), "model B stream did not start"
        wait_active(MODEL_B)
        stop_daemon(proc)
        assert box["done"].wait(30), "active stream did not end after daemon stop"
        proc = start_daemon("max1", max1_cfg, daemon_env(ld))
        _, models = req("GET", "/api/v1/models")
        model = next(m for m in models["models"] if m["ref"] == MODEL_B)
        assert model["preload"] == "preloaded" and model["resident"] == "stopped", model
        wait_no_resident(timeout=15)
        log("restart with active stream: preload kept, resident stopped", box["error"])

        # Warm the resident before opening the stream used for the busy-unload
        # check; otherwise the first request also pays model startup time and
        # the stream can finish before the 1 s drain wait.
        assert_chat(MODEL_B)
        box = stream_in_thread(MODEL_B)
        assert box["started"].wait(120), "model B stream did not start"
        wait_active(MODEL_B)
        status, body = req("POST", "/api/v1/models/unload", {"ref": MODEL_B}, timeout=30)
        assert status == 409 and body["error"]["code"] == "model_busy", (status, body)
        status, body = req("POST", "/api/v1/models/unload", {"ref": MODEL_B, "wait_seconds": 1}, timeout=30)
        # A warm 0.3B model can finish inside the 1 s window; the timeout path
        # itself is covered by the scheduler lifecycle unit test.
        if status == 200:
            assert box["done"].is_set(), "unload drained while the stream was active"
            assert body["preload"] == "absent", body
            log("busy unload 409/200 (stream finished in the wait window)")
        else:
            assert status == 409 and body["error"]["code"] == "model_busy", (status, body)
            status, body = req("POST", "/api/v1/models/unload", {"ref": MODEL_B, "force": True}, timeout=120)
            assert status == 200 and body["preload"] == "absent", (status, body)
            assert box["done"].wait(60), "forced stream did not end"
            log("busy unload 409/409/force ok, stream ended:", box["error"])
        wait_no_resident(timeout=15)
    finally:
        stop_daemon(proc)

    log("PUBLIC_SCHEDULER_E2E_PASS")
    log("home:", HOME)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        log("FAIL:", exc)
        sys.exit(1)
