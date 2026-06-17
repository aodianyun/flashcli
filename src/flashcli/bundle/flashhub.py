"""Re-export protocol FlashHub client (host CLI)."""

from flashcli_bundle.flashhub import (
    RepoFile,
    RepoIndex,
    download_manifest_from_repo,
    download_repo_file,
    fetch_repo_index,
)

__all__ = [
    "RepoFile",
    "RepoIndex",
    "download_manifest_from_repo",
    "download_repo_file",
    "fetch_repo_index",
]
