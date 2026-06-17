"""FlashHub repository metadata API and file download (protocol layer)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flashcli_bundle import paths as config
from flashcli_bundle.flashhub_errors import flashhub_error_from_fetch
from flashcli_bundle.util.download_progress import download_url_to_path, fetch_json_url
from flashcli_bundle.version import __version__

_CDN_PATH_RE = re.compile(r"/repo/\d+/versions/\d+/(.*)$")


@dataclass(frozen=True)
class RepoFile:
    path: str
    url: str
    size: int | None = None
    md5: str | None = None

    @classmethod
    def from_flashhub_entry(cls, data: dict[str, Any]) -> RepoFile | None:
        url = str(data.get("download_url") or "").strip()
        if not url:
            return None
        path = _path_from_download_url(url)
        if not path:
            return None
        size_raw = data.get("file_size")
        size = int(size_raw) if size_raw is not None else None
        md5 = str(data.get("md5_hash") or "").strip().lower() or None
        return cls(path=path, url=url, size=size, md5=md5)


@dataclass
class RepoIndex:
    repo_url: str
    files: list[RepoFile]

    def find(self, rel_path: str) -> RepoFile | None:
        want = rel_path.strip().lstrip("/")
        for entry in self.files:
            if entry.path == want:
                return entry
        for entry in self.files:
            if entry.path.endswith("/" + want) or entry.path.split("/")[-1] == want.split("/")[-1]:
                return entry
        return None

    def manifest_path(self) -> str:
        return "flashcli-bundle.json"


def _path_from_download_url(url: str) -> str | None:
    """Extract bundle-relative path from FlashHub CDN ``download_url``."""
    parsed = urlparse(url)
    match = _CDN_PATH_RE.search(parsed.path)
    if match:
        rel = match.group(1).strip("/")
        return rel or None
    tail = parsed.path.lstrip("/")
    return tail or None


def _unwrap_flashhub_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("FlashHub response must be a JSON object")
    code = payload.get("code")
    if code is not None and int(code) != 0:
        message = str(payload.get("message") or "unknown error")
        raise RuntimeError(f"FlashHub API error (code={code}): {message}")
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    raise RuntimeError(
        "FlashHub response missing data object. "
        "Expected { code: 0, data: { files: [...] } }."
    )


def _index_cache_path(repo_url: str) -> Path:
    key = hashlib.sha256(repo_url.strip().encode()).hexdigest()[:16]
    return config.CACHE_DIR / "repo-index" / f"{key}.json"


def _normalize_repo_url(repo_url: str) -> str:
    return repo_url.strip().rstrip("/")


def _parse_index_payload(payload: Any, *, repo_url: str) -> RepoIndex:
    repo_url = _normalize_repo_url(repo_url)
    data = _unwrap_flashhub_payload(payload)
    raw_files = data.get("files")
    if not isinstance(raw_files, list):
        raise RuntimeError(
            f"FlashHub repo {repo_url!r} missing data.files array."
        )

    files: list[RepoFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        entry = RepoFile.from_flashhub_entry(item)
        if entry is not None:
            files.append(entry)

    if not files:
        raise RuntimeError(
            f"FlashHub repo {repo_url!r} returned no downloadable files."
        )
    return RepoIndex(repo_url=repo_url, files=files)


def fetch_repo_index(repo_url: str, *, use_cache: bool = True) -> RepoIndex:
    repo_url = _normalize_repo_url(repo_url)
    cache = _index_cache_path(repo_url)
    if use_cache and cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            return _parse_index_payload(payload, repo_url=repo_url)
        except (json.JSONDecodeError, RuntimeError, ValueError, TypeError):
            pass

    try:
        payload = fetch_json_url(
            repo_url,
            label=f"FlashHub repo ({repo_url[:64]}…)",
            user_agent=f"flashcli/{__version__}",
        )
    except RuntimeError as exc:
        raise flashhub_error_from_fetch(repo_url, exc) from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return _parse_index_payload(payload, repo_url=repo_url)


def download_repo_file(
    entry: RepoFile,
    dest: Path,
    *,
    quiet: bool = False,
    force: bool = False,
) -> Path:
    dest = dest.expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and not force:
        if entry.md5 and _file_md5(dest) == entry.md5:
            if not quiet:
                print(f"Using cached {entry.path}", file=sys.stderr)
            return dest
        if not entry.md5:
            if not quiet:
                print(f"Using existing {entry.path}", file=sys.stderr)
            return dest

    download_url_to_path(
        entry.url,
        dest,
        quiet=quiet,
        label=f"bundle file {entry.path}",
        user_agent=f"flashcli/{__version__}",
        timeout=600,
    )

    if entry.md5:
        got = _file_md5(dest)
        if got != entry.md5:
            dest.unlink(missing_ok=True)
            raise RuntimeError(
                f"MD5 mismatch for {entry.path}: expected {entry.md5}, got {got}"
            )
    return dest


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_manifest_from_repo(
    repo_url: str,
    dest: Path,
    *,
    quiet: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    index = fetch_repo_index(repo_url)
    entry = index.find(index.manifest_path())
    if entry is None:
        raise FileNotFoundError(
            f"No flashcli-bundle.json in FlashHub repo {repo_url!r}. "
            f"Available: {', '.join(f.path for f in index.files[:12])}"
            + (" …" if len(index.files) > 12 else "")
        )
    download_repo_file(entry, dest, quiet=quiet, force=force)
    return json.loads(dest.read_text(encoding="utf-8"))
