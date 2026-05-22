"""Resolve model bundle version as a git ref (tag/branch/commit name)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from flashcli.bundle.catalog import effective_bundle_cfg_for_preset, raw_bundle_cfg
from flashcli.models.registry import Preset
from flashcli.runtime.detect import GpuInfo

_REF_SAFE_RE = re.compile(r"[^A-Za-z0-9._+-]+")


def _bundle_cfg(preset: Preset, *, gpu: GpuInfo | None = None) -> dict[str, Any]:
    return effective_bundle_cfg_for_preset(preset, gpu=gpu)


def _git_cfg(preset: Preset, *, gpu: GpuInfo | None = None) -> dict[str, Any]:
    cfg = _bundle_cfg(preset, gpu=gpu)
    git = cfg.get("git")
    return dict(git) if isinstance(git, dict) else {}


def is_bundle_root(path: Path) -> bool:
    return path.is_dir() and (path / "flashcli-bundle.json").is_file()


def sanitize_git_ref(ref: str) -> str:
    """Filesystem-safe directory name for a git ref."""
    ref = ref.strip()
    if not ref:
        return "main"
    return _REF_SAFE_RE.sub("_", ref)


def list_catalog_refs(preset: Preset) -> dict[str, dict[str, Any]]:
    """Declared refs from ``bundle.refs`` (legacy alias: ``bundle.versions``)."""
    cfg = raw_bundle_cfg(preset)
    raw = cfg.get("refs") or cfg.get("versions") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, meta in raw.items():
        name = str(key).strip()
        if not name:
            continue
        out[name] = dict(meta) if isinstance(meta, dict) else {}
    return out


def resolve_requested_git_ref(
    preset: Preset,
    ref_override: str | None = None,
) -> str:
    """CLI override > bundle.git.ref > bundle.ref > refs[].default > ``main``."""
    if ref_override is not None:
        ref = str(ref_override).strip()
        if not ref:
            raise ValueError("git ref must be non-empty")
        return ref

    cfg = _bundle_cfg(preset)
    git = _git_cfg(preset)

    for key in ("ref",):
        pinned = str(git.get(key, "")).strip()
        if pinned:
            return pinned

    pinned = str(cfg.get("ref", "")).strip()
    if pinned:
        return pinned

    legacy = str(cfg.get("version", "")).strip()
    if legacy:
        return legacy

    catalog = list_catalog_refs(preset)
    for name, meta in catalog.items():
        if meta.get("default"):
            return name

    return "main"


def validate_ref_in_catalog(preset: Preset, git_ref: str) -> None:
    catalog = list_catalog_refs(preset)
    if catalog and git_ref not in catalog:
        known = ", ".join(sorted(catalog))
        raise ValueError(
            f"Git ref {git_ref!r} is not listed in models.yaml bundle.refs "
            f"for preset {preset.name!r}. Known: {known}"
        )


def read_bundle_git_ref(bundle_root: Path) -> str | None:
    import json

    path = bundle_root / "flashcli-bundle.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for key in ("git_ref", "bundle_version", "version"):
        val = data.get(key)
        if val:
            return str(val)
    return None
