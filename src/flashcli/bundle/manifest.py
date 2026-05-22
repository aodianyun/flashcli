"""Parse flashcli-model-bundle manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUNDLE_FORMAT = "flashcli-model-bundle"
_LEGACY_MANIFEST = "manifest.json"
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


def bundle_format_version(bundle: BundleManifest) -> int:
    try:
        return int(bundle.raw.get("format_version", 1))
    except (TypeError, ValueError):
        return 1


def bundle_python_root(bundle: BundleManifest) -> Path:
    """Directory prepended to PYTHONPATH for ``entry`` imports."""
    root = bundle.bundle_root.resolve()
    if bundle_format_version(bundle) >= 2:
        return root
    legacy_py = bundle.runtime_dir / "python"
    if legacy_py.is_dir():
        return legacy_py.resolve()
    return root


def _legacy_runtime_manifest_path(bundle: BundleManifest) -> Path | None:
    for candidate in (
        bundle.runtime_dir / _LEGACY_MANIFEST,
        bundle.bundle_root / "runtime" / _LEGACY_MANIFEST,
    ):
        if candidate.is_file():
            return candidate
    return None


def bundle_runtime_config(bundle: BundleManifest) -> dict[str, Any]:
    """Runtime fields from merged ``flashcli-bundle.json`` or legacy ``manifest.json``."""
    raw = bundle.raw
    if isinstance(raw.get("python_dependencies"), dict) or raw.get("modules") is not None:
        return raw
    legacy = _legacy_runtime_manifest_path(bundle)
    if legacy is not None:
        return json.loads(legacy.read_text(encoding="utf-8"))
    return raw


def bundle_modules(bundle: BundleManifest) -> list[dict[str, Any]]:
    mods = bundle_runtime_config(bundle).get("modules")
    if not isinstance(mods, list):
        return []
    return [m for m in mods if isinstance(m, dict)]


def bundle_cuda_config(bundle: BundleManifest) -> dict[str, Any]:
    cuda = bundle_runtime_config(bundle).get("cuda")
    return dict(cuda) if isinstance(cuda, dict) else {}


def module_file_path(bundle: BundleManifest, file_rel: str) -> Path:
    """Resolve ``modules[].file`` relative to bundle root (v2) or legacy runtime dir."""
    rel = file_rel.strip().lstrip("/")
    if bundle_format_version(bundle) >= 2:
        return (bundle.bundle_root / rel).resolve()
    if rel.startswith("lib/"):
        return (bundle.runtime_dir / rel).resolve()
    return (bundle.bundle_root / rel).resolve()


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
    runtime_rel = str(data.get("runtime_dir", ".")).strip() or "."
    if runtime_rel in (".", ""):
        runtime_dir = root
    else:
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
    """Legacy: read ``runtime/manifest.json`` only."""
    path = runtime_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Runtime manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    fmt = data.get("format", "")
    if fmt and fmt != RUNTIME_FORMAT:
        raise ValueError(f"Unsupported runtime manifest format: {fmt!r}")
    return data


def _entry_module_path(bundle: BundleManifest, spec: EntrySpec) -> Path | None:
    parts = spec.module.split(".")
    if not parts:
        return None
    py_root = bundle_python_root(bundle)
    return py_root.joinpath(*parts[:-1], f"{parts[-1]}.py")


def validate_bundle_layout(bundle: BundleManifest) -> list[str]:
    """Return validation errors (empty if OK). Supports v2 flat and legacy trees."""
    errors: list[str] = []
    py_root = bundle_python_root(bundle)
    if bundle_format_version(bundle) < 2:
        if not bundle.runtime_dir.is_dir():
            errors.append(f"runtime dir not found: {bundle.runtime_dir}")
            return errors

    cfg = bundle_runtime_config(bundle)
    if bundle_format_version(bundle) >= 2:
        if not isinstance(cfg.get("python_dependencies"), dict):
            errors.append(
                "flashcli-bundle.json missing python_dependencies "
                "(merge runtime manifest into bundle json)"
            )
    else:
        try:
            if not isinstance(cfg.get("python_dependencies"), dict):
                load_runtime_manifest(bundle.runtime_dir)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

    for cap, spec in (
        ("run", bundle.entry_run),
        ("serve", bundle.entry_serve),
    ):
        if cap not in bundle.capabilities or spec is None:
            continue
        mod_path = _entry_module_path(bundle, spec)
        if mod_path is None or not mod_path.is_file():
            errors.append(
                f"entry.{cap} module file not found: {mod_path} "
                f"(module {spec.module!r} under {py_root})"
            )

    if "run" in bundle.capabilities and bundle.entry_run is None:
        errors.append("capabilities includes 'run' but entry.run is missing")
    if "serve" in bundle.capabilities and bundle.entry_serve is None:
        errors.append("capabilities includes 'serve' but entry.serve is missing")

    for mod in bundle_modules(bundle):
        file_rel = str(mod.get("file", "")).strip()
        if not file_rel:
            errors.append("modules[] entry missing file")
            continue
        if mod.get("optional"):
            continue
        path = module_file_path(bundle, file_rel)
        if not path.is_file():
            errors.append(f"required native module missing: {path}")

    from flashcli.bundle.weights import validate_weights_spec

    errors.extend(validate_weights_spec(bundle))
    return errors
