"""Local markers for cached bundle runtimes (protocol layer)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flashcli_bundle import paths as config
from flashcli_bundle.preset import Preset
from flashcli_bundle.preset_ref import preset_cache_key, resolve_preset

_MARKER = ".runtime.json"
_PRESET_MARKER = ".flashcli_bundle.json"


def runtime_dir(runtime_id: str) -> Path:
    return config.RUNTIMES_DIR / runtime_id


def marker_path(runtime_id: str) -> Path:
    return runtime_dir(runtime_id) / _MARKER


def read_runtime_marker(runtime_id: str) -> dict[str, Any] | None:
    path = marker_path(runtime_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_runtime_marker(runtime_id: str, data: dict[str, Any]) -> None:
    root = runtime_dir(runtime_id)
    root.mkdir(parents=True, exist_ok=True)
    marker_path(runtime_id).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def _marker_dir_for_preset(preset: Preset | str) -> Path:
    if isinstance(preset, str):
        key = resolve_preset(preset).cache_key
    else:
        key = preset_cache_key(preset)
    return config.BUNDLES_DIR / key


def preset_marker_path(preset: Preset | str) -> Path:
    return _marker_dir_for_preset(preset) / _PRESET_MARKER


def read_preset_marker(preset: Preset | str) -> dict[str, Any] | None:
    path = preset_marker_path(preset)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_preset_marker(preset: Preset, data: dict[str, Any]) -> None:
    key = preset_cache_key(preset)
    payload = dict(data)
    payload.setdefault("ref", preset.name)
    payload.setdefault("cache_key", key)
    path = config.BUNDLES_DIR / key / _PRESET_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def list_cached_presets() -> list[dict[str, Any]]:
    """Scan bundle markers under ``BUNDLES_DIR``."""
    root = config.BUNDLES_DIR
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for marker_file in sorted(root.glob(f"**/{_PRESET_MARKER}")):
        if not marker_file.is_file():
            continue
        try:
            data = json.loads(marker_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        entry = dict(data)
        try:
            rel = marker_file.parent.relative_to(root)
            entry.setdefault("cache_key", str(rel))
        except ValueError:
            entry.setdefault("cache_key", marker_file.parent.name)
        entries.append(entry)
    return entries
