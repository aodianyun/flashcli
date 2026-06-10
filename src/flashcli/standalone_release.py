"""python-build-standalone release helpers (stdlib only — no flashcli imports)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from http.client import IncompleteRead
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_STANDALONE_TAG = os.environ.get("FLASHCLI_PYTHON_STANDALONE_TAG", "20260602")
GITHUB_REPO = "astral-sh/python-build-standalone"
DEFAULT_GIT_PROXY_PREFIX = "https://mirror.ghproxy.com/"

KNOWN_TRIPLETS = (
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "riscv64-unknown-linux-gnu",
    "loongarch64-unknown-linux-gnu",
    "s390x-unknown-linux-gnu",
    "ppc64le-unknown-linux-gnu",
)

_ASSET_NAME_RE = re.compile(
    r"^cpython-(?P<ver>3\.(?P<minor>\d+)\.(?P<patch>\d+)(?P<pre>[a-z]+\d+)?)"
    r"\+(?P<tag>[0-9]+)-(?P<triplet>.+)-install_only\.tar\.gz$"
)


@dataclass(frozen=True)
class StandaloneAsset:
    py_minor: str
    triplet: str
    tag: str
    filename: str
    url: str
    size: int | None = None
    md5: str | None = None

    @property
    def rel_path(self) -> str:
        return f"standalone/{self.tag}/{self.triplet}/{self.filename}"

    def to_manifest_entry(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "py_minor": self.py_minor,
            "triplet": self.triplet,
            "tag": self.tag,
            "path": self.rel_path,
            "filename": self.filename,
            "url": self.url,
        }
        if self.size is not None:
            out["size"] = self.size
        if self.md5 is not None:
            out["md5"] = self.md5
        return out


def py_minor_tag(major: int, minor: int) -> str:
    return f"{major}{minor:02d}"


def parse_py_minors_csv(raw: str) -> list[str] | None:
    text = raw.strip().lower()
    if not text or text == "all":
        return None
    out: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit() and len(part) == 3:
            out.append(part)
            continue
        raise ValueError(f"Invalid python minor {part!r} (expected 310,311,312 or 'all')")
    return out or None


def _github_release_api_url(tag: str) -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}"


def _github_download_base(tag: str) -> str:
    return f"https://github.com/{GITHUB_REPO}/releases/download/{tag}"


def _github_release_page_urls(tag: str) -> list[tuple[str, str]]:
    return [
        ("release page", f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}"),
        (
            "expanded assets",
            f"https://github.com/{GITHUB_REPO}/releases/expanded_assets/{tag}",
        ),
    ]


def _git_proxy_disabled() -> bool:
    return (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )


def _github_download_urls(url: str) -> list[tuple[str, str]]:
    if not url.startswith("https://github.com/"):
        return [(url, "download")]
    direct = url
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(candidate: str, label: str) -> None:
        if candidate not in seen:
            seen.add(candidate)
            out.append((candidate, label))

    prefer_proxy = os.environ.get("FLASHCLI_PREFER_GITHUB_MIRROR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) or os.environ.get("FLASHCLI_USE_MIRROR", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    proxy = (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip()
    proxies: list[str] = []
    if proxy and not _git_proxy_disabled() and proxy.lower() not in ("auto", ""):
        proxies.append(proxy.rstrip("/") + "/")
    if DEFAULT_GIT_PROXY_PREFIX.rstrip("/") + "/" not in proxies and not _git_proxy_disabled():
        proxies.append(DEFAULT_GIT_PROXY_PREFIX.rstrip("/") + "/")

    proxied = [p + direct for p in proxies]

    if prefer_proxy:
        for candidate in proxied:
            add(candidate, "GitHub mirror")
        add(direct, "GitHub")
    else:
        add(direct, "GitHub")
        for candidate in proxied:
            add(candidate, "GitHub mirror")
    return out


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
    retries: int = 3,
) -> bytes:
    hdrs = {
        "User-Agent": "flashcli-pack-python-standalone/1.0",
        "Accept": "*/*",
    }
    if headers:
        hdrs.update(headers)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=hdrs)  # noqa: S310
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                chunks: list[bytes] = []
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
        except (HTTPError, URLError, TimeoutError, OSError, IncompleteRead) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(attempt * 2, 6))
                continue
            break
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_error}") from last_error


def _cache_root() -> Path:
    return Path(
        os.environ.get(
            "FLASHCLI_PYTHON_RELEASE_CACHE",
            Path.home() / ".flashcli" / "python" / ".cache",
        )
    ).expanduser()


def _parse_install_only_names(html: str, tag: str) -> list[str]:
    pattern = re.compile(
        rf"cpython-3\.\d+\.\d+(?:[a-z]+\d+)?\+{re.escape(tag)}-[^\"'\s<>]+-install_only\.tar\.gz"
    )
    names = sorted(set(pattern.findall(html)))
    return [n for n in names if _ASSET_NAME_RE.match(n)]


def _synthetic_release_payload(tag: str, filenames: list[str]) -> dict[str, Any]:
    base = _github_download_base(tag)
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"{base}/{name}",
            }
            for name in filenames
        ],
    }


def _fetch_release_via_html(tag: str, *, quiet: bool = False) -> dict[str, Any]:
    names: set[str] = set()
    last_error: Exception | None = None
    for label, page_url in _github_release_page_urls(tag):
        for candidate, source in _github_download_urls(page_url):
            try:
                html = _http_get(candidate, timeout=180).decode("utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                last_error = exc
                continue
            found = _parse_install_only_names(html, tag)
            if found:
                names.update(found)
                if not quiet:
                    print(f"[i] Release index via {source} ({label})", file=sys.stderr)
                break
        if names:
            break
    if not names:
        raise RuntimeError(
            f"Cannot parse install_only assets for {tag!r} from GitHub release pages: {last_error}"
        )
    return _synthetic_release_payload(tag, sorted(names))


def fetch_release_json(tag: str, *, quiet: bool = False) -> dict[str, Any]:
    cache_file = _cache_root() / f"github-release-{tag}.json"
    if cache_file.is_file() and os.environ.get("FLASHCLI_REFRESH_RELEASE_CACHE", "") != "1":
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None

    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = _github_release_api_url(tag)
    for candidate, source in _github_download_urls(api_url):
        try:
            raw = _http_get(candidate, headers=headers, timeout=120)
            payload = json.loads(raw.decode("utf-8"))
            if not quiet:
                print(f"[i] Release index via {source}", file=sys.stderr)
            break
        except HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                raise RuntimeError(
                    f"python-build-standalone release {tag!r} not found on GitHub"
                ) from exc
            continue
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            continue

    if payload is None:
        if cache_file.is_file():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if not quiet:
            print(
                f"[i] GitHub API unavailable ({last_error}); trying release HTML …",
                file=sys.stderr,
            )
        payload = _fetch_release_via_html(tag, quiet=quiet)

    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid release payload for {tag!r}")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def download_file(
    url: str,
    dest: Path,
    *,
    quiet: bool = False,
    timeout: float = 600,
) -> None:
    dest = dest.expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial.unlink(missing_ok=True)
    last_error: Exception | None = None

    for candidate, source in _github_download_urls(url):
        if not quiet:
            print(f"Downloading {source}: {dest.name}", file=sys.stderr)
        try:
            req = Request(candidate, headers={"User-Agent": "flashcli-pack-python-standalone/1.0"})
            with urlopen(req, timeout=timeout) as resp, partial.open("wb") as out:  # noqa: S310
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            partial.replace(dest)
            if not quiet:
                print(f"Download complete: {dest} ({dest.stat().st_size} bytes)", file=sys.stderr)
            return
        except (HTTPError, URLError, TimeoutError, OSError, IncompleteRead, RuntimeError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if not quiet:
                print(f"Download failed ({source}): {exc}", file=sys.stderr)

    raise RuntimeError(f"Failed to download {url}: {last_error}")


def assets_from_release(
    payload: dict[str, Any],
    *,
    tag: str | None = None,
) -> list[StandaloneAsset]:
    release_tag = str(tag or payload.get("tag_name") or "").strip()
    if not release_tag:
        raise RuntimeError("Release payload missing tag_name")

    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise RuntimeError(f"Release {release_tag!r} has no assets[]")

    out: list[StandaloneAsset] = []
    base = _github_download_base(release_tag)
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        match = _ASSET_NAME_RE.match(name)
        if not match or match.group("tag") != release_tag:
            continue
        minor = int(match.group("minor"))
        py_minor = py_minor_tag(3, minor)
        url = str(item.get("browser_download_url") or "").strip() or f"{base}/{name}"
        size_raw = item.get("size")
        size = int(size_raw) if size_raw is not None else None
        out.append(
            StandaloneAsset(
                py_minor=py_minor,
                triplet=match.group("triplet"),
                tag=release_tag,
                filename=name,
                url=url,
                size=size,
            )
        )
    return out


def filter_assets(
    assets: list[StandaloneAsset],
    *,
    triplets: set[str],
    py_minors: list[str] | None,
    include_pre_release: bool = False,
) -> list[StandaloneAsset]:
    selected: list[StandaloneAsset] = []
    for asset in assets:
        if asset.triplet not in triplets:
            continue
        if py_minors is not None and asset.py_minor not in py_minors:
            continue
        if not include_pre_release:
            m = _ASSET_NAME_RE.match(asset.filename)
            if m and m.group("pre"):
                continue
        selected.append(asset)
    selected.sort(key=lambda a: (a.triplet, int(a.py_minor), a.filename))
    return selected


def find_standalone_asset(
    py_minor: str,
    triplet: str,
    *,
    tag: str | None = None,
    quiet: bool = False,
) -> StandaloneAsset:
    release_tag = tag or DEFAULT_STANDALONE_TAG
    payload = fetch_release_json(release_tag, quiet=quiet)
    assets = assets_from_release(payload, tag=release_tag)
    for asset in assets:
        if asset.py_minor == py_minor and asset.triplet == triplet:
            return asset
    raise RuntimeError(
        f"No install_only build for Python {py_minor[0]}.{py_minor[1:]} "
        f"on {triplet} in release {release_tag!r}"
    )


def standalone_download_url(
    py_minor: str,
    triplet: str,
    *,
    tag: str | None = None,
    quiet: bool = False,
) -> str:
    return find_standalone_asset(py_minor, triplet, tag=tag, quiet=quiet).url


def write_manifest(
    assets: list[StandaloneAsset],
    dest: Path,
    *,
    tag: str,
) -> None:
    payload = {
        "format": "flashcli-python-standalone",
        "format_version": 1,
        "standalone_tag": tag,
        "upstream": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
        "files": [a.to_manifest_entry() for a in assets],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid manifest: {path}")
    return data


def asset_from_manifest(
    manifest: dict[str, Any],
    py_minor: str,
    triplet: str,
) -> StandaloneAsset | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    tag = str(manifest.get("standalone_tag") or "")
    for item in files:
        if not isinstance(item, dict):
            continue
        if str(item.get("py_minor")) != py_minor or str(item.get("triplet")) != triplet:
            continue
        filename = str(item.get("filename") or Path(str(item.get("path", ""))).name)
        url = str(item.get("url") or "")
        if not filename:
            continue
        if not url:
            base = _github_download_base(tag)
            url = f"{base}/{filename}"
        size_raw = item.get("size")
        return StandaloneAsset(
            py_minor=py_minor,
            triplet=triplet,
            tag=tag,
            filename=filename,
            url=url,
            size=int(size_raw) if size_raw is not None else None,
            md5=str(item.get("md5") or "").lower() or None,
        )
    return None
