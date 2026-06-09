"""Stable runtime cache identity for a bundle source."""

from __future__ import annotations

import hashlib
import re

_SAFE = re.compile(r"[^A-Za-z0-9._+-]+")


def runtime_id_from_repo(repo_url: str, bundle_name: str) -> str:
    digest = hashlib.sha256(repo_url.strip().encode()).hexdigest()[:12]
    safe = _SAFE.sub("-", bundle_name.strip()).strip("-") or "bundle"
    return f"{safe}-{digest}"


def runtime_id_from_path(path: str, bundle_name: str) -> str:
    digest = hashlib.sha256(path.strip().encode()).hexdigest()[:12]
    safe = _SAFE.sub("-", bundle_name.strip()).strip("-") or "bundle"
    return f"{safe}-local-{digest}"
