"""ModelScope Hub download — host-only weight pull."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from flashcli.util.hub_quiet import suppress_hub_side_logs


def _import_snapshot_download() -> Any:
    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "ModelScope weights require the modelscope package. "
            "Install with: pip install 'modelscope>=1.11'"
        ) from exc
    return snapshot_download


def ms_endpoint_from_spec(spec: Mapping[str, Any]) -> tuple[str, bool]:
    """Return (endpoint URL, True when set in spec or MODELSCOPE_ENDPOINT)."""
    from_spec = str(spec.get("endpoint", "")).strip()
    if from_spec:
        return from_spec.rstrip("/"), True
    from_env = os.environ.get("MODELSCOPE_ENDPOINT", "").strip()
    if from_env:
        return from_env.rstrip("/"), True
    return "", False


def modelscope_revision_attempts(revision: str | None) -> list[str | None]:
    """Revision candidates for ModelScope (HF ``main`` → ``master``)."""
    if revision is None:
        return [None]
    rev = str(revision).strip()
    if not rev:
        return [None]
    if rev.lower() == "main":
        return ["master", None]
    out: list[str | None] = [rev]
    if rev.lower() == "master":
        out.append(None)
    elif rev not in ("master",):
        out.append(None)
    return out


def is_ms_revision_not_found(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "no revision" in msg or (
        type(exc).__name__ == "NotExistError" and "revision" in msg
    )


@contextlib.contextmanager
def _ms_download_env(endpoint: str) -> Iterator[None]:
    prev_endpoint = os.environ.get("MODELSCOPE_ENDPOINT")
    try:
        if endpoint:
            os.environ["MODELSCOPE_ENDPOINT"] = endpoint.rstrip("/")
        yield
    finally:
        if prev_endpoint is None:
            os.environ.pop("MODELSCOPE_ENDPOINT", None)
        else:
            os.environ["MODELSCOPE_ENDPOINT"] = prev_endpoint


def run_ms_snapshot_download(
    model_id: str,
    dest: Path,
    *,
    revision: str | None = None,
    allow_patterns: list[str] | None = None,
    endpoint: str = "",
    quiet: bool = False,
) -> None:
    """Download *model_id* into *dest* via ModelScope ``snapshot_download``."""
    snapshot_download = _import_snapshot_download()
    dest.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "model_id": model_id,
        "local_dir": str(dest),
    }
    if revision:
        kwargs["revision"] = revision
    if allow_patterns:
        kwargs["allow_patterns"] = allow_patterns

    if not quiet:
        label = endpoint or os.environ.get("MODELSCOPE_ENDPOINT") or "modelscope.cn"
        print(f"ModelScope download: {model_id} -> {dest} ({label})", flush=True)

    with suppress_hub_side_logs(), _ms_download_env(endpoint):
        snapshot_download(**kwargs)
