"""Local markers for cached bundle runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flashcli import config

_MARKER = ".runtime.json"


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


def preset_marker_path(preset_name: str) -> Path:
    return config.BUNDLES_DIR / preset_name / ".flashcli_bundle.json"


def read_preset_marker(preset_name: str) -> dict[str, Any] | None:
    path = preset_marker_path(preset_name)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_preset_marker(preset_name: str, data: dict[str, Any]) -> None:
    path = preset_marker_path(preset_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
