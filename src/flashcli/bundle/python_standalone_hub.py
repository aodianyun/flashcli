"""FlashHub-first python-build-standalone resolution and download."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from flashcli import config
from flashcli._version import __version__
from flashcli.standalone_release import (
    DEFAULT_STANDALONE_TAG,
    StandaloneAsset,
    _github_download_base,
    asset_from_manifest,
    find_standalone_asset,
    load_manifest,
)

from flashcli_bundle.paths import (
    default_python_standalone_repo_url,
    python_standalone_repo_url,
)

DEFAULT_PYTHON_REPO = default_python_standalone_repo_url()

_MANIFEST_NAME = "python-standalone.json"


def python_repo_url() -> str | None:
    """FlashHub repo API URL for python-standalone (``FLASHCLI_PYTHON_REPO``)."""
    return python_standalone_repo_url()


def _is_flashhub_url(url: str) -> bool:
    host = url.lower()
    return "flashhub" in host or "aodianyun.com" in host


def _manifest_cache_path(repo_url: str) -> Path:
    key = hashlib.sha256(repo_url.encode()).hexdigest()[:16]
    return config.CACHE_DIR / "python-standalone" / f"{key}-manifest.json"


def _entry_basename(path: str) -> str:
    return unquote(path.strip("/").split("/")[-1])


def _files_by_basename(index) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for entry in index.files:
        name = _entry_basename(entry.path)
        if name:
            out.setdefault(name, []).append(entry)
    return out


def flashhub_tarball_urls(index, filename: str) -> list[str]:
    """All FlashHub CDN URLs for *filename* (handles duplicate path layouts)."""
    want = unquote(filename.strip())
    seen: set[str] = set()
    urls: list[str] = []
    for entry in index.files:
        name = _entry_basename(entry.path)
        if not name.endswith(".tar.gz"):
            continue
        if name == want and entry.url not in seen:
            seen.add(entry.url)
            urls.append(entry.url)
    return urls


def enrich_manifest_from_index(manifest: dict[str, Any], index) -> dict[str, Any]:
    """Replace manifest ``url``/``md5``/``size`` with FlashHub CDN metadata when present."""
    by_name = _files_by_basename(index)
    files = manifest.get("files")
    if not isinstance(files, list):
        return manifest

    enriched: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        filename = str(row.get("filename") or Path(str(row.get("path", ""))).name)
        entries = by_name.get(filename) or []
        if entries:
            entry = entries[0]
            row["url"] = entry.url
            if entry.md5:
                row["md5"] = entry.md5
            if entry.size is not None:
                row["size"] = entry.size
            if len(entries) > 1:
                row["flashhub_urls"] = [e.url for e in entries]
        enriched.append(row)
    return {**manifest, "files": enriched}


def _manifest_needs_cdn_enrich(manifest: dict[str, Any]) -> bool:
    """True when any tarball row still points outside FlashHub CDN."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return True
    for item in files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or Path(str(item.get("path", ""))).name)
        if not filename.endswith(".tar.gz"):
            continue
        if not _is_flashhub_url(str(item.get("url") or "")):
            return True
    return False


def fetch_flashhub_manifest(
    repo_url: str,
    *,
    quiet: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Load ``python-standalone.json`` from FlashHub and merge CDN download URLs."""
    from flashcli.bundle.flashhub import fetch_repo_index
    from flashcli.util.download_progress import fetch_json_url

    cache = _manifest_cache_path(repo_url)
    if not force and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("files"):
                if not _manifest_needs_cdn_enrich(cached):
                    return cached
                # Stale cache kept GitHub urls when %2B basename matching failed;
                # re-enrich from the current repo index without re-downloading JSON.
                index = fetch_repo_index(repo_url, use_cache=True)
                enriched = enrich_manifest_from_index(cached, index)
                if not _manifest_needs_cdn_enrich(enriched):
                    cache.write_text(
                        json.dumps(enriched, indent=2) + "\n", encoding="utf-8"
                    )
                    return enriched
        except (json.JSONDecodeError, TypeError, OSError, RuntimeError):
            pass

    index = fetch_repo_index(repo_url, use_cache=not force)
    manifest_entry = index.find(_MANIFEST_NAME)
    if manifest_entry is None:
        raise FileNotFoundError(
            f"No {_MANIFEST_NAME} in FlashHub repo {repo_url!r}. "
            f"Upload dist/python-standalone/{_MANIFEST_NAME} with the tarballs."
        )

    payload = fetch_json_url(
        manifest_entry.url,
        quiet=quiet,
        label=f"FlashHub {_MANIFEST_NAME}",
        user_agent=f"flashcli/{__version__}",
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid {_MANIFEST_NAME} from {repo_url!r}")

    enriched = enrich_manifest_from_index(payload, index)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(enriched, indent=2) + "\n", encoding="utf-8")
    return enriched


def _local_manifest_path() -> Path | None:
    override = os.environ.get("FLASHCLI_PYTHON_STANDALONE_MANIFEST", "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    bundled = config.FLASHCLI_HOME / "python-standalone" / _MANIFEST_NAME
    if bundled.is_file():
        return bundled
    dist = config.package_root() / "dist" / "python-standalone" / _MANIFEST_NAME
    if dist.is_file():
        return dist
    return None


def resolve_standalone_asset(
    py_minor: str,
    triplet: str,
    *,
    tag: str | None = None,
    quiet: bool = False,
) -> StandaloneAsset:
    """FlashHub manifest → local manifest → GitHub release index."""
    release_tag = tag or DEFAULT_STANDALONE_TAG
    last_error: Exception | None = None

    repo = python_repo_url()
    if repo:
        try:
            manifest = fetch_flashhub_manifest(repo, quiet=quiet)
            asset = asset_from_manifest(manifest, py_minor, triplet)
            if asset is not None:
                if not quiet:
                    if _is_flashhub_url(asset.url):
                        source = asset.url
                    else:
                        source = (
                            f"{repo} (tarball URL not on CDN yet; "
                            f"will try FlashHub index then fallback)"
                        )
                    print(
                        f"Using python-standalone {asset.filename} from {source}",
                        file=sys.stderr,
                    )
                return asset
            last_error = RuntimeError(
                f"No {py_minor}/{triplet} in FlashHub manifest ({repo})"
            )
        except Exception as exc:
            last_error = exc
            if not quiet:
                print(
                    f"FlashHub python-standalone unavailable ({exc}); trying fallbacks …",
                    file=sys.stderr,
                )

    local = _local_manifest_path()
    if local is not None:
        asset = asset_from_manifest(load_manifest(local), py_minor, triplet)
        if asset is not None:
            if not quiet:
                print(
                    f"Using python-standalone {asset.filename} from local manifest {local}",
                    file=sys.stderr,
                )
            return asset

    return find_standalone_asset(py_minor, triplet, tag=release_tag, quiet=quiet)


def standalone_download_urls(
    asset: StandaloneAsset,
    *,
    repo_url: str | None = None,
    extra_flashhub_urls: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Ordered URLs: FlashHub CDN (all known paths) → GitHub → GitHub mirror."""
    from flashcli.runtime.mirror import github_release_download_urls

    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(url: str, label: str) -> None:
        url = url.strip()
        if url and url not in seen:
            seen.add(url)
            out.append((url, label))

    flashhub_candidates: list[str] = []
    if extra_flashhub_urls:
        flashhub_candidates.extend(extra_flashhub_urls)
    if asset.url and _is_flashhub_url(asset.url):
        flashhub_candidates.insert(0, asset.url)
    if repo_url:
        try:
            from flashcli.bundle.flashhub import fetch_repo_index

            index = fetch_repo_index(repo_url)
            flashhub_candidates.extend(flashhub_tarball_urls(index, asset.filename))
        except Exception:
            pass
    for i, url in enumerate(dict.fromkeys(flashhub_candidates)):
        add(url, "FlashHub" if i == 0 else f"FlashHub alt{i}")

    if asset.url and not _is_flashhub_url(asset.url):
        add(asset.url, "manifest")

    github_base = f"{_github_download_base(asset.tag)}/{asset.filename}"
    for candidate, label in github_release_download_urls(github_base):
        add(candidate, label)

    return out


def _verify_md5(path: Path, want: str) -> None:
    got = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            got.update(chunk)
    digest = got.hexdigest()
    if digest != want.lower():
        raise RuntimeError(
            f"MD5 mismatch for {path.name}: expected {want}, got {digest}"
        )


def download_standalone_asset(
    asset: StandaloneAsset,
    dest: Path,
    *,
    quiet: bool = False,
    timeout: float = 3600,
    repo_url: str | None = None,
    extra_flashhub_urls: list[str] | None = None,
) -> int:
    """Download tarball with FlashHub → GitHub → mirror fallback."""
    from flashcli.util.download_progress import download_url_to_path

    dest = dest.expanduser()
    repo = repo_url if repo_url is not None else python_repo_url()
    last_error: Exception | None = None
    label = f"Python {asset.py_minor[0]}.{asset.py_minor[1:]} ({asset.tag})"

    def attempt(*, refresh_flashhub: bool) -> int | None:
        nonlocal last_error
        if refresh_flashhub and repo:
            try:
                fetch_flashhub_manifest(repo, quiet=quiet, force=True)
                from flashcli.bundle.flashhub import fetch_repo_index

                fetch_repo_index(repo, use_cache=False)
            except Exception as exc:
                if not quiet:
                    print(
                        f"FlashHub manifest refresh failed: {exc}",
                        file=sys.stderr,
                    )
        urls = standalone_download_urls(
            asset,
            repo_url=repo,
            extra_flashhub_urls=extra_flashhub_urls,
        )
        for url, source in urls:
            display = f"{label} [{source}]"
            try:
                nbytes = download_url_to_path(
                    url,
                    dest,
                    quiet=quiet,
                    label=display,
                    timeout=timeout,
                )
                if asset.md5:
                    _verify_md5(dest, asset.md5)
                return nbytes
            except RuntimeError as exc:
                last_error = exc
                dest.unlink(missing_ok=True)
                if not quiet:
                    print(f"Download failed ({source}): {exc}", file=sys.stderr)
        return None

    for refresh in (False, True):
        got = attempt(refresh_flashhub=refresh)
        if got is not None:
            return got

    raise RuntimeError(
        f"Failed to download standalone Python {asset.filename}"
        + (f": {last_error}" if last_error else "")
    ) from last_error
