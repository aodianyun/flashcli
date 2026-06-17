"""Hugging Face Hub download — set HF_ENDPOINT and delegate to the official CLI."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from flashcli.util.hub_quiet import (
    apply_hub_quiet_env,
    hf_download_verbose,
    suppress_hub_side_logs,
)

HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
HF_OFFICIAL_ENDPOINT = "https://huggingface.co"


def _hub_timeout_seconds(env_key: str, flashcli_key: str, default: str) -> str:
    if os.environ.get(env_key, "").strip():
        return os.environ[env_key].strip()
    return os.environ.get(flashcli_key, default).strip() or default


def apply_hub_timeouts(env: dict[str, str] | None = None) -> dict[str, str]:
    """Apply Hub timeouts (``HF_HUB_*``; flashcli defaults: etag 30s, download 300s)."""
    out = dict(env) if env is not None else os.environ.copy()
    out.setdefault(
        "HF_HUB_ETAG_TIMEOUT",
        _hub_timeout_seconds("HF_HUB_ETAG_TIMEOUT", "FLASHCLI_HF_ETAG_TIMEOUT", "30"),
    )
    out.setdefault(
        "HF_HUB_DOWNLOAD_TIMEOUT",
        _hub_timeout_seconds(
            "HF_HUB_DOWNLOAD_TIMEOUT", "FLASHCLI_HF_DOWNLOAD_TIMEOUT", "300"
        ),
    )
    return out


def _hf_max_workers() -> int | None:
    raw = os.environ.get("FLASHCLI_HF_MAX_WORKERS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _apply_flashcli_hub_timeouts() -> None:
    """Set short Hub timeouts on the current process (for ``hf download`` child)."""
    for key, value in apply_hub_timeouts().items():
        if key.startswith("HF_HUB_") and key in (
            "HF_HUB_ETAG_TIMEOUT",
            "HF_HUB_DOWNLOAD_TIMEOUT",
        ):
            os.environ[key] = value


def _prefer_mirror_hub_first() -> bool:
    if os.environ.get("FLASHCLI_NO_MIRROR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    return os.environ.get("FLASHCLI_PREFER_HF_MIRROR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def download_endpoint_order(endpoint: str, *, explicit: bool) -> list[str]:
    """Endpoints to try. Empty string = official Hub (unset HF_ENDPOINT)."""
    ep = endpoint.strip().rstrip("/") if endpoint else ""
    if explicit:
        return [ep] if ep else [""]
    if _prefer_mirror_hub_first():
        return [HF_MIRROR_ENDPOINT, ""]
    return ["", HF_MIRROR_ENDPOINT]


def hub_probe_timeout() -> float:
    raw = os.environ.get("FLASHCLI_HF_PROBE_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    raw = os.environ.get("HF_HUB_ETAG_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 3.0


def hub_api_probe_url(
    base: str, *, repo: str | None = None, revision: str | None = None
) -> str:
    ep = base.strip().rstrip("/") or HF_OFFICIAL_ENDPOINT
    if repo:
        rev = quote(str(revision or "main"), safe="")
        return f"{ep}/api/models/{repo}/revision/{rev}"
    return ep


def hub_reachable(
    base: str,
    *,
    repo: str | None = None,
    revision: str | None = None,
    timeout: float | None = None,
) -> bool:
    """Quick GET probe (seconds) — avoid a full ``hf download`` when Hub is down."""
    url = hub_api_probe_url(base, repo=repo, revision=revision)
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout or hub_probe_timeout()) as resp:
            return resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def filter_download_endpoints(
    endpoints: list[str],
    *,
    repo: str,
    revision: str | None,
    quiet: bool,
) -> list[str]:
    """Drop official Hub when a short probe fails (``hf download`` retries are slow)."""
    if os.environ.get("FLASHCLI_SKIP_HF_PROBE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return endpoints
    out: list[str] = []
    for ep in endpoints:
        if ep:
            out.append(ep)
            continue
        if hub_reachable(HF_OFFICIAL_ENDPOINT, repo=repo, revision=revision):
            out.append(ep)
        elif not quiet and hf_download_verbose():
            print(
                f"Skipping {HF_OFFICIAL_ENDPOINT} (unreachable in "
                f"{hub_probe_timeout():g}s); using mirror next ...",
                file=sys.stderr,
            )
    if out:
        return out
    if HF_MIRROR_ENDPOINT in endpoints:
        return [HF_MIRROR_ENDPOINT]
    return endpoints


def endpoint_label(endpoint: str) -> str:
    return endpoint.strip().rstrip("/") or "huggingface.co (default)"


@contextlib.contextmanager
def hub_endpoint_env(endpoint: str) -> Iterator[str]:
    """Set HF_ENDPOINT for child Hub tools (same as ``hf download`` / ``huggingface-cli``)."""
    key = "HF_ENDPOINT"
    prev = os.environ.get(key)
    ep = endpoint.strip().rstrip("/") if endpoint else ""
    try:
        if ep:
            os.environ[key] = ep
            if ep != HF_OFFICIAL_ENDPOINT:
                if os.environ.get("FLASHCLI_DISABLE_XET", "").strip().lower() not in (
                    "0",
                    "false",
                    "no",
                ):
                    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        elif key in os.environ:
            del os.environ[key]
        _apply_flashcli_hub_timeouts()
        yield ep or HF_OFFICIAL_ENDPOINT
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev


def hub_cli_on_path() -> str | None:
    """Resolved Hub download CLI (``hf`` preferred)."""
    return shutil.which("hf") or shutil.which("huggingface-cli")


def _hf_cli_command(
    repo: str,
    dest: Path,
    *,
    revision: str | None,
    allow_patterns: list[str] | None,
) -> list[str]:
    hf = hub_cli_on_path()
    if hf:
        cmd = [hf, "download", repo, "--local-dir", str(dest)]
    else:
        # Same entry point as pip console_scripts when scripts dir is not on PATH.
        cmd = [
            sys.executable,
            "-m",
            "huggingface_hub.cli.hf",
            "download",
            repo,
            "--local-dir",
            str(dest),
        ]
    if revision:
        cmd.extend(["--revision", revision])
    if allow_patterns:
        for pattern in allow_patterns:
            cmd.extend(["--include", pattern])
    max_workers = _hf_max_workers()
    if max_workers is not None:
        cmd.extend(["--max-workers", str(max_workers)])
    return cmd


def _stderr_tail(stderr: str | None, *, max_lines: int = 12) -> str:
    if not stderr:
        return ""
    lines = stderr.strip().splitlines()
    if len(lines) <= max_lines:
        return stderr.strip()
    return "\n".join(lines[-max_lines:])


def run_hf_cli_download(
    repo: str,
    dest: Path,
    *,
    revision: str | None = None,
    endpoint: str = "",
    allow_patterns: list[str] | None = None,
    quiet: bool = False,
    extra_env: Mapping[str, str] | None = None,
) -> None:
    """Download a model repo using the official Hub CLI (respects HF_ENDPOINT)."""
    dest.mkdir(parents=True, exist_ok=True)
    with hub_endpoint_env(endpoint):
        cmd = _hf_cli_command(
            repo, dest, revision=revision, allow_patterns=allow_patterns
        )
        hub = os.environ.get("HF_ENDPOINT", HF_OFFICIAL_ENDPOINT).rstrip("/")
        if not quiet and hf_download_verbose():
            rev_note = f" (revision={revision})" if revision else ""
            print(
                f"Downloading HuggingFace weights: {repo}{rev_note}\n"
                f"  Hub: {hub}\n"
                f"  CLI: {' '.join(cmd)}\n"
                f"  -> {dest}",
                file=sys.stderr,
            )
        env = apply_hub_timeouts()
        if extra_env:
            env.update(extra_env)
        token = (
            os.environ.get("HF_TOKEN", "").strip()
            or os.environ.get("HUGGING_FACE_HUB_TOKEN", "").strip()
        )
        if token and "--token" not in cmd:
            cmd.extend(["--token", token])
        if quiet:
            env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        else:
            env = apply_hub_quiet_env(env)
        if quiet:
            result = subprocess.run(
                cmd,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return
            detail = _stderr_tail(result.stderr)
        else:
            # Stream stderr so tqdm stays live; suppress flashcli + Hub INFO in parent.
            with suppress_hub_side_logs():
                result = subprocess.run(cmd, env=env, check=False)
            if result.returncode == 0:
                if not quiet and not hf_download_verbose():
                    print(f"Downloaded {repo} -> {dest}", file=sys.stderr)
                return
            detail = f"exit code {result.returncode}"
        raise RuntimeError(
            f"Hub CLI download failed for {repo!r} (HF_ENDPOINT={hub!r})"
            + (f":\n{detail}" if detail else "")
        )
