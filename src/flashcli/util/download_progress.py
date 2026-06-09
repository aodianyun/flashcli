"""HTTP download helpers with tqdm progress (unless ``quiet``)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, BinaryIO, Mapping
from urllib.error import URLError
from urllib.request import Request, urlopen

_DEFAULT_CHUNK = 1024 * 1024


def format_bytes(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KiB"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} MiB"
    return f"{num / (1024 * 1024 * 1024):.2f} GiB"


def content_length(resp: object) -> int | None:
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Content-Length") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        size = int(str(raw).strip())
    except ValueError:
        return None
    return size if size > 0 else None


def copy_stream_with_progress(
    src: BinaryIO,
    dest: BinaryIO,
    *,
    total: int | None,
    label: str,
    quiet: bool,
    chunk_size: int = _DEFAULT_CHUNK,
) -> int:
    """Copy *src* → *dest*, updating a tqdm bar when not ``quiet``."""
    written = 0
    if quiet:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            dest.write(chunk)
            written += len(chunk)
        return written

    from tqdm import tqdm

    desc = label[:48] + ("…" if len(label) > 48 else "")
    bar = tqdm(
        total=total,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        desc=desc,
        file=sys.stderr,
        leave=True,
    )
    try:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            dest.write(chunk)
            written += len(chunk)
            bar.update(len(chunk))
    finally:
        bar.close()
    return written


def download_url_to_path(
    url: str,
    dest: Path,
    *,
    quiet: bool = False,
    headers: Mapping[str, str] | None = None,
    timeout: float = 600,
    label: str | None = None,
    user_agent: str | None = None,
) -> int:
    """Download *url* to *dest* (atomic via ``.part``). Returns byte count."""
    dest = dest.expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f"{dest.name}.part")
    partial.unlink(missing_ok=True)

    hdrs = dict(headers or {})
    if user_agent:
        hdrs.setdefault("User-Agent", user_agent)

    req = Request(url, headers=hdrs)  # noqa: S310
    display = label or url
    if not quiet:
        print(f"Downloading {display}", file=sys.stderr)

    try:
        with urlopen(req, timeout=timeout) as resp, partial.open("wb") as out:
            total = content_length(resp)
            nbytes = copy_stream_with_progress(
                resp,
                out,
                total=total,
                label=display,
                quiet=quiet,
            )
    except URLError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(dest)
    if not quiet:
        size = dest.stat().st_size
        print(f"Download complete ({format_bytes(size)}): {dest}", file=sys.stderr)
    return dest.stat().st_size


def fetch_json_url(
    url: str,
    *,
    quiet: bool = False,
    headers: Mapping[str, str] | None = None,
    timeout: float = 120,
    label: str | None = None,
    user_agent: str | None = None,
) -> Any:
    """GET *url* and parse JSON body."""
    hdrs = dict(headers or {})
    if user_agent:
        hdrs.setdefault("User-Agent", user_agent)
    hdrs.setdefault("Accept", "application/json")
    req = Request(url, headers=hdrs)  # noqa: S310
    display = label or url
    if not quiet:
        print(f"Fetching {display}", file=sys.stderr)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}: {exc}") from exc
