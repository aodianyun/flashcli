"""GitHub release download with mirror fallback (host only)."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from flashcli_bundle.runtime.mirror import (
    DEFAULT_GIT_PROXY_PREFIX,
    apply_mirror_env,
    mirror_enabled,
)

_GIT_PROXY_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


def _git_proxy_disabled() -> bool:
    import os

    return (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip().lower() in _GIT_PROXY_DISABLED_VALUES


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def _prefer_github_mirror_first() -> bool:
    import os

    apply_mirror_env()
    if _truthy(os.environ.get("FLASHCLI_NO_MIRROR")):
        return False
    if _git_proxy_disabled():
        return False
    if _truthy(os.environ.get("FLASHCLI_PREFER_GITHUB_MIRROR")):
        return True
    return mirror_enabled()


def _github_proxy_prefixes() -> list[str]:
    import os

    apply_mirror_env()
    if _git_proxy_disabled():
        return []
    prefixes: list[str] = []
    explicit = (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip()
    if explicit and explicit.lower() not in ("auto", ""):
        prefixes.append(explicit.rstrip("/") + "/")
    elif mirror_enabled():
        prefixes.append(DEFAULT_GIT_PROXY_PREFIX)
    if DEFAULT_GIT_PROXY_PREFIX not in prefixes:
        prefixes.append(DEFAULT_GIT_PROXY_PREFIX)
    return prefixes


def proxied_github_url(url: str, proxy_prefix: str) -> str:
    prefix = proxy_prefix.rstrip("/") + "/"
    if url.startswith(prefix):
        return url
    return f"{prefix}{url}"


def github_release_download_urls(url: str) -> list[tuple[str, str]]:
    apply_mirror_env()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "github.com":
        return [(url, "download")]

    direct = url
    proxies = [
        proxied_github_url(direct, prefix) for prefix in _github_proxy_prefixes()
    ]
    prefer_proxy = _prefer_github_mirror_first()

    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(candidate: str, label: str) -> None:
        if candidate not in seen:
            seen.add(candidate)
            out.append((candidate, label))

    if prefer_proxy:
        for candidate in proxies:
            add(candidate, "GitHub mirror")
        add(direct, "GitHub")
    else:
        add(direct, "GitHub")
        for candidate in proxies:
            add(candidate, "GitHub mirror")
    return out


def download_github_release_asset(
    url: str,
    dest: Path,
    *,
    quiet: bool = False,
    label: str | None = None,
    timeout: float = 600,
) -> int:
    from flashcli.util.download_progress import download_url_to_path

    last_error: Exception | None = None
    for candidate, source in github_release_download_urls(url):
        display = label or f"{source} asset"
        try:
            return download_url_to_path(
                candidate,
                dest,
                quiet=quiet,
                label=display,
                timeout=timeout,
            )
        except RuntimeError as exc:
            last_error = exc
            if not quiet:
                print(
                    f"Download failed ({source}): {exc}",
                    file=sys.stderr,
                )
    raise RuntimeError(
        f"Failed to download GitHub release asset {url}"
        + (f": {last_error}" if last_error else "")
    ) from last_error
