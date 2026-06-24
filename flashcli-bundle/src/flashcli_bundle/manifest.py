"""Parse flashcli-model-bundle manifests (format_version 3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BUNDLE_FORMAT = "flashcli-model-bundle"
BUNDLE_FORMAT_VERSION = 3

EntryMode = Literal["engine", "script"]
_VALID_ENTRY_MODES = frozenset({"engine", "script"})


@dataclass(frozen=True)
class EntrySpec:
    module: str
    attr: str
    mode: EntryMode = "engine"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EntrySpec | None:
        if not data or not isinstance(data, dict):
            return None
        mod = str(data.get("module", "")).strip()
        attr = str(data.get("attr", "")).strip()
        if not mod or not attr:
            return None
        raw_mode = str(data.get("mode", "engine")).strip().lower() or "engine"
        mode: EntryMode = "engine"
        if raw_mode in _VALID_ENTRY_MODES:
            mode = raw_mode  # type: ignore[assignment]
        return cls(module=mod, attr=attr, mode=mode)


def entry_mode_for_capability(bundle: BundleManifest, capability: str) -> EntryMode:
    if capability == "run":
        return bundle.entry_run.mode if bundle.entry_run else "engine"
    if capability == "serve":
        return bundle.entry_serve.mode if bundle.entry_serve else "engine"
    return "engine"


@dataclass
class BundleManifest:
    bundle_root: Path
    name: str
    capabilities: list[str]
    entry_run: EntrySpec | None
    entry_serve: EntrySpec | None
    description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


def bundle_format_version(bundle: BundleManifest) -> int:
    try:
        return int(bundle.raw.get("format_version", 0))
    except (TypeError, ValueError):
        return 0


def bundle_protocol_version(bundle: BundleManifest) -> int:
    """Manifest ``protocol_version`` — must match installed ``flashcli-bundle``."""
    if "protocol_version" not in bundle.raw:
        raise ValueError(
            f"Bundle {bundle.name!r} missing required field protocol_version "
            f"(current flashcli-bundle protocol is 1)"
        )
    raw = bundle.raw["protocol_version"]
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Bundle {bundle.name!r} has invalid protocol_version {raw!r} "
            f"(expected integer, e.g. 1)"
        ) from exc


def check_bundle_protocol_version(bundle: BundleManifest) -> None:
    """Raise if manifest protocol does not match installed ``flashcli-bundle``."""
    from flashcli_bundle.version import PROTOCOL_VERSION

    manifest_ver = bundle_protocol_version(bundle)
    if manifest_ver != PROTOCOL_VERSION:
        raise ValueError(
            f"Bundle {bundle.name!r} protocol_version={manifest_ver} does not match "
            f"installed flashcli-bundle protocol {PROTOCOL_VERSION}. "
            f"Upgrade flashcli / flashcli-bundle or republish the bundle."
        )


def require_v3(bundle: BundleManifest) -> None:
    if bundle.raw.get("format") != BUNDLE_FORMAT:
        raise ValueError(
            f"Unsupported bundle format: {bundle.raw.get('format')!r} "
            f"(expected {BUNDLE_FORMAT!r})"
        )
    ver = bundle_format_version(bundle)
    if ver != BUNDLE_FORMAT_VERSION:
        raise ValueError(
            f"Unsupported format_version {ver} (expected {BUNDLE_FORMAT_VERSION}). "
            "Upgrade the bundle release or use a matching flashcli version."
        )
    check_bundle_protocol_version(bundle)


def bundle_python_root(bundle: BundleManifest) -> Path:
    return bundle.bundle_root.resolve()


def bundle_python_abi(bundle: BundleManifest) -> str:
    abi = str(bundle.raw.get("python_abi", "")).strip()
    if not abi or not abi.isdigit() or len(abi) != 3:
        raise ValueError(
            f"Bundle {bundle.name!r} missing valid python_abi (expected e.g. '312')"
        )
    return abi


def _runtime_map_from_raw(raw: dict[str, Any]) -> dict[str, str]:
    block = raw.get("runtime")
    if not isinstance(block, dict) or not block:
        raise ValueError("missing runtime map (env_key → runtime/<env-key>/ path)")
    out = {
        str(k).strip(): str(v).strip()
        for k, v in block.items()
        if str(k).strip() and str(v).strip()
    }
    if not out:
        raise ValueError("runtime map is empty")
    return out


def bundle_runtime_map(bundle: BundleManifest) -> dict[str, str]:
    return _runtime_map_from_raw(bundle.raw)


def bundle_runtime_matrix(bundle: BundleManifest) -> list[str]:
    return sorted(bundle_runtime_map(bundle))


def bundle_runtime_dir(bundle: BundleManifest, env_key: str) -> Path:
    runtime_map = bundle_runtime_map(bundle)
    rel = str(runtime_map.get(env_key, "")).strip().lstrip("/")
    if not rel:
        raise ValueError(
            f"Bundle {bundle.name!r} has no runtime path for env {env_key!r}"
        )
    return (bundle.bundle_root / rel).resolve()


def _capabilities_from_data(
    entry_run: EntrySpec | None,
    entry_serve: EntrySpec | None,
) -> list[str]:
    caps: list[str] = []
    if entry_run is not None:
        caps.append("run")
    if entry_serve is not None:
        caps.append("serve")
    return caps


def load_bundle_manifest(bundle_root: Path) -> BundleManifest:
    root = bundle_root.expanduser().resolve()
    path = root / "flashcli-bundle.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Model bundle missing flashcli-bundle.json: {path}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return load_bundle_manifest_data(data, bundle_root=root)


def load_bundle_manifest_data(data: dict[str, Any], *, bundle_root: Path) -> BundleManifest:
    entry = data.get("entry") or {}
    entry_run = EntrySpec.from_dict(entry.get("run") if isinstance(entry, dict) else None)
    entry_serve = EntrySpec.from_dict(
        entry.get("serve") if isinstance(entry, dict) else None
    )
    manifest = BundleManifest(
        bundle_root=bundle_root,
        name=str(data.get("name", bundle_root.name)),
        capabilities=_capabilities_from_data(entry_run, entry_serve),
        entry_run=entry_run,
        entry_serve=entry_serve,
        description=str(data.get("description", "")),
        raw=data,
    )
    require_v3(manifest)
    return manifest


def validate_bundle_protocol_version(bundle: BundleManifest) -> list[str]:
    """Return validation errors for ``protocol_version`` (empty if OK)."""
    errors: list[str] = []
    try:
        check_bundle_protocol_version(bundle)
    except ValueError as exc:
        errors.append(str(exc))
    return errors
