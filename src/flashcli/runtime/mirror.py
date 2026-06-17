"""China-friendly mirror endpoints (protocol re-export + host GitHub release download)."""

from flashcli.runtime.mirror_github import (
    download_github_release_asset,
    github_release_download_urls,
    proxied_github_url,
)
from flashcli_bundle.runtime.mirror import (
    DEFAULT_GIT_PROXY_PREFIX,
    MIRROR_ENV_FILE,
    MIRROR_HF_ENDPOINT,
    MIRROR_PIP_INDEX_URL,
    MIRROR_PIP_TRUSTED_HOST,
    MIRROR_TORCH_INDEX_BASE,
    apply_mirror_env,
    git_proxy_status,
    mirror_enabled,
    mirror_status_lines,
    pip_index_url,
    pip_install_extra_args,
    pip_trusted_host,
    resolve_torch_index_url,
)

__all__ = [
    "DEFAULT_GIT_PROXY_PREFIX",
    "MIRROR_ENV_FILE",
    "MIRROR_HF_ENDPOINT",
    "MIRROR_PIP_INDEX_URL",
    "MIRROR_PIP_TRUSTED_HOST",
    "MIRROR_TORCH_INDEX_BASE",
    "apply_mirror_env",
    "download_github_release_asset",
    "git_proxy_status",
    "github_release_download_urls",
    "mirror_enabled",
    "mirror_status_lines",
    "pip_index_url",
    "pip_install_extra_args",
    "pip_trusted_host",
    "proxied_github_url",
    "resolve_torch_index_url",
]
