"""China-friendly mirror endpoints for pip / PyTorch / Hugging Face."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from flashcli.config import FLASHCLI_HOME

MIRROR_ENV_FILE = "mirror.env"

MIRROR_PIP_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
MIRROR_PIP_TRUSTED_HOST = "mirrors.aliyun.com"
MIRROR_HF_ENDPOINT = "https://hf-mirror.com"
MIRROR_TORCH_INDEX_BASE = "https://mirrors.aliyun.com/pytorch-wheels"
DEFAULT_GIT_PROXY_PREFIX = "https://mirror.ghproxy.com/"

_APPLIED = False


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def mirror_enabled() -> bool:
    if _truthy(os.environ.get("FLASHCLI_USE_MIRROR")):
        return True
    if _truthy(os.environ.get("FLASHCLI_NO_MIRROR")):
        return False
    return FLASHCLI_HOME.joinpath(MIRROR_ENV_FILE).is_file()


def _load_mirror_env_file() -> None:
    path = FLASHCLI_HOME / MIRROR_ENV_FILE
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def apply_mirror_env() -> None:
    """Load ``~/.flashcli/mirror.env`` and default mirror URLs (idempotent)."""
    global _APPLIED
    if _APPLIED:
        return
    _load_mirror_env_file()
    if mirror_enabled():
        os.environ.setdefault("PIP_INDEX_URL", MIRROR_PIP_INDEX_URL)
        os.environ.setdefault("PIP_TRUSTED_HOST", MIRROR_PIP_TRUSTED_HOST)
        os.environ.setdefault("HF_ENDPOINT", MIRROR_HF_ENDPOINT)
        os.environ.setdefault("FLASHCLI_PREFER_HF_MIRROR", "1")
        if not _git_proxy_disabled():
            os.environ.setdefault("FLASHCLI_GIT_PROXY", DEFAULT_GIT_PROXY_PREFIX)
    _APPLIED = True


def _git_proxy_disabled() -> bool:
    return (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )


def _prefer_github_mirror_first() -> bool:
    apply_mirror_env()
    if _git_proxy_disabled():
        return False
    if _truthy(os.environ.get("FLASHCLI_PREFER_GITHUB_MIRROR")):
        return True
    return mirror_enabled()


def _github_proxy_prefixes() -> list[str]:
    """Proxy base URLs for ``https://github.com/...`` downloads (deduped)."""
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
    """Rewrite a GitHub HTTPS URL through a ghproxy-style prefix."""
    prefix = proxy_prefix.rstrip("/") + "/"
    if url.startswith(prefix):
        return url
    return f"{prefix}{url}"


def github_release_download_urls(url: str) -> list[tuple[str, str]]:
    """Ordered download candidates for GitHub release assets."""
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
    """Download a GitHub release asset with mirror / fallback support."""
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


def git_proxy_status() -> str | None:
    apply_mirror_env()
    if _git_proxy_disabled():
        return None
    explicit = (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip()
    if explicit and explicit.lower() not in ("auto", ""):
        return explicit.rstrip("/") + "/"
    if mirror_enabled():
        return DEFAULT_GIT_PROXY_PREFIX
    return DEFAULT_GIT_PROXY_PREFIX + " (fallback only)"


def pip_index_url() -> str | None:
    apply_mirror_env()
    url = os.environ.get("PIP_INDEX_URL", "").strip()
    return url or None


def pip_trusted_host() -> str | None:
    apply_mirror_env()
    host = os.environ.get("PIP_TRUSTED_HOST", "").strip()
    return host or None


def pip_install_extra_args() -> list[str]:
    """Extra ``pip install`` flags for PyPI mirror (non-torch packages)."""
    apply_mirror_env()
    out: list[str] = []
    index = pip_index_url()
    if index:
        out.extend(["--index-url", index])
        host = pip_trusted_host()
        if host:
            out.extend(["--trusted-host", host])
    return out


def resolve_torch_index_url(torch_index: str) -> str:
    """PyTorch wheel index — Aliyun mirror when mirror mode is on."""
    apply_mirror_env()
    name = torch_index if torch_index.startswith("cu") else f"cu{torch_index}"
    if mirror_enabled():
        return f"{MIRROR_TORCH_INDEX_BASE}/{name}/"
    from flashcli.runtime.detect import torch_index_url

    return torch_index_url(name)


def mirror_status_lines() -> list[str]:
    apply_mirror_env()
    if not mirror_enabled():
        lines = [
            "[i] Mirror: off (set FLASHCLI_USE_MIRROR=1 or re-run install.sh --mirror)"
        ]
        proxy = git_proxy_status()
        if proxy and not _git_proxy_disabled():
            lines.append(f"     FLASHCLI_GIT_PROXY={proxy}")
        return lines
    lines = [
        "[ok] Mirror: on",
        f"     PIP_INDEX_URL={os.environ.get('PIP_INDEX_URL', MIRROR_PIP_INDEX_URL)}",
        f"     HF_ENDPOINT={os.environ.get('HF_ENDPOINT', MIRROR_HF_ENDPOINT)}",
    ]
    proxy = git_proxy_status()
    if proxy:
        lines.append(f"     FLASHCLI_GIT_PROXY={proxy}")
    env_file = FLASHCLI_HOME / MIRROR_ENV_FILE
    if env_file.is_file():
        lines.append(f"     config: {env_file}")
    return lines
