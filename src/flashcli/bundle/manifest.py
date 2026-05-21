"""Parse flashcli-model-bundle and runtime manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BUNDLE_FORMAT = "flashcli-model-bundle"
RUNTIME_FORMAT = "flashrt-runtime-manifest"


@dataclass(frozen=True)
class EntrySpec:
    module: str
    attr: str

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EntrySpec | None:
        if not data or not isinstance(data, dict):
            return None
        mod = str(data.get("module", "")).strip()
        attr = str(data.get("attr", "")).strip()
        if not mod or not attr:
            return None
        return cls(module=mod, attr=attr)


@dataclass
class BundleManifest:
    bundle_root: Path
    name: str
    runtime_dir: Path
    capabilities: list[str]
    entry_run: EntrySpec | None
    entry_serve: EntrySpec | None
    description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


def load_bundle_manifest(bundle_root: Path) -> BundleManifest:
    root = bundle_root.expanduser().resolve()
    path = root / "flashcli-bundle.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Model bundle missing flashcli-bundle.json: {path}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != BUNDLE_FORMAT:
        raise ValueError(
            f"Unsupported bundle format: {data.get('format')!r} "
            f"(expected {BUNDLE_FORMAT!r})"
        )
    runtime_rel = str(data.get("runtime_dir", "runtime")).strip() or "runtime"
    runtime_dir = (root / runtime_rel).resolve()
    entry = data.get("entry") or {}
    caps = data.get("capabilities") or []
    if not isinstance(caps, list):
        caps = []
    capabilities = [str(c) for c in caps]
    return BundleManifest(
        bundle_root=root,
        name=str(data.get("name", root.name)),
        runtime_dir=runtime_dir,
        capabilities=capabilities,
        entry_run=EntrySpec.from_dict(entry.get("run") if isinstance(entry, dict) else None),
        entry_serve=EntrySpec.from_dict(
            entry.get("serve") if isinstance(entry, dict) else None
        ),
        description=str(data.get("description", "")),
        raw=data,
    )


def load_runtime_manifest(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Runtime manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    fmt = data.get("format", "")
    if fmt and fmt != RUNTIME_FORMAT:
        raise ValueError(f"Unsupported runtime manifest format: {fmt!r}")
    return data


def validate_bundle_layout(bundle: BundleManifest) -> list[str]:
    """Return list of validation errors (empty if OK)."""
    errors: list[str] = []
    if not bundle.runtime_dir.is_dir():
        errors.append(f"runtime dir not found: {bundle.runtime_dir}")
        return errors
    py_root = bundle.runtime_dir / "python"
    if not py_root.is_dir():
        errors.append(f"runtime/python/ missing: {py_root}")
    elif not (py_root / "partner").is_dir() and not (bundle.bundle_root / "partner").is_dir():
        errors.append(
            "partner/ missing — add bundle_root/partner/ or runtime/python/partner/ "
            "(entry modules for run/serve)"
        )
    try:
        load_runtime_manifest(bundle.runtime_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    if "run" in bundle.capabilities and bundle.entry_run is None:
        errors.append("capabilities includes 'run' but entry.run is missing")
    if "serve" in bundle.capabilities and bundle.entry_serve is None:
        errors.append("capabilities includes 'serve' but entry.serve is missing")
    from flashcli.bundle.weights import validate_weights_spec

    errors.extend(validate_weights_spec(bundle))
    return errors
