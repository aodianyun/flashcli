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

EntryKind = Literal["python", "native-exec", "native-abi"]
VALID_ENTRY_KINDS = frozenset({"python", "native-exec", "native-abi"})
NATIVE_ENTRY_KINDS = frozenset({"native-exec", "native-abi"})


def merge_native_spec(
    base: dict[str, Any] | None, override: dict[str, Any] | None
) -> dict[str, Any]:
    """Deep-merge a capability native spec over the entry-level default."""
    if not isinstance(base, dict):
        base = {}
    if not isinstance(override, dict):
        return dict(base)
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_native_spec(out[key], value)
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class EntrySpec:
    module: str
    attr: str
    mode: EntryMode = "engine"
    kind: str = "python"
    native: dict[str, Any] = field(default_factory=dict)

    @property
    def is_native(self) -> bool:
        return self.kind in NATIVE_ENTRY_KINDS

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        default_kind: str = "python",
        default_native: dict[str, Any] | None = None,
    ) -> EntrySpec | None:
        if not data or not isinstance(data, dict):
            return None
        kind = str(data.get("kind", default_kind)).strip().lower() or "python"
        native = merge_native_spec(default_native, data.get("native"))
        mod = str(data.get("module", "")).strip()
        attr = str(data.get("attr", "")).strip()
        raw_mode = str(data.get("mode", "engine")).strip().lower() or "engine"
        mode: EntryMode = "engine"
        if raw_mode in _VALID_ENTRY_MODES:
            mode = raw_mode  # type: ignore[assignment]
        if kind == "python" and (not mod or not attr):
            return None
        return cls(module=mod, attr=attr, mode=mode, kind=kind, native=native)


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


def _optional_int_field(bundle: BundleManifest, name: str) -> int | None:
    if name not in bundle.raw:
        return None
    raw = bundle.raw[name]
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Bundle {bundle.name!r} has invalid {name} {raw!r} (expected integer)"
        ) from exc


def bundle_runtime_abi_version(bundle: BundleManifest) -> int | None:
    """Manifest ``runtime_abi_version`` (native model-runtime face), or None."""
    return _optional_int_field(bundle, "runtime_abi_version")


def bundle_exec_protocol_version(bundle: BundleManifest) -> int | None:
    """Manifest ``exec_protocol_version`` (native-exec framing), or None."""
    return _optional_int_field(bundle, "exec_protocol_version")


def check_bundle_execution_versions(bundle: BundleManifest) -> None:
    """Raise if native execution version axes are missing or mismatched."""
    from flashcli_bundle.version import EXEC_PROTOCOL_VERSION, RUNTIME_ABI_VERSION

    kinds = {
        spec.kind
        for spec in (bundle.entry_run, bundle.entry_serve)
        if spec is not None
    }
    abi_ver = bundle_runtime_abi_version(bundle)
    exec_ver = bundle_exec_protocol_version(bundle)

    if "native-abi" in kinds:
        if abi_ver is None:
            raise ValueError(
                f"Bundle {bundle.name!r} uses entry.kind=native-abi but is missing "
                f"required runtime_abi_version (expected {RUNTIME_ABI_VERSION})"
            )
        if abi_ver != RUNTIME_ABI_VERSION:
            raise ValueError(
                f"Bundle {bundle.name!r} runtime_abi_version={abi_ver} does not match "
                f"supported native model-runtime ABI {RUNTIME_ABI_VERSION}. "
                f"Upgrade flashcli or republish the bundle."
            )
    elif abi_ver is not None:
        raise ValueError(
            f"Bundle {bundle.name!r} sets runtime_abi_version but has no native-abi entry"
        )

    if "native-exec" in kinds:
        if exec_ver is None:
            raise ValueError(
                f"Bundle {bundle.name!r} uses entry.kind=native-exec but is missing "
                f"required exec_protocol_version (expected {EXEC_PROTOCOL_VERSION})"
            )
        if exec_ver != EXEC_PROTOCOL_VERSION:
            raise ValueError(
                f"Bundle {bundle.name!r} exec_protocol_version={exec_ver} does not match "
                f"supported native-exec protocol {EXEC_PROTOCOL_VERSION}. "
                f"Upgrade flashcli or republish the bundle."
            )
    elif exec_ver is not None:
        raise ValueError(
            f"Bundle {bundle.name!r} sets exec_protocol_version but has no native-exec entry"
        )


def _validate_native_exec_native(cap: str, native: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    command = native.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(a, str) and a for a in command
    ):
        errors.append(f"entry.{cap}.native.command must be a non-empty array of strings")
    transport = str(native.get("transport", "stdio")).strip().lower() or "stdio"
    if transport not in ("stdio", "http"):
        errors.append(f"entry.{cap}.native.transport must be 'stdio' or 'http', got {transport!r}")
    cwd = str(native.get("cwd", "bundle")).strip() or "bundle"
    if cwd != "bundle" and not cwd.startswith("/"):
        errors.append(f"entry.{cap}.native.cwd must be 'bundle' or an absolute path, got {cwd!r}")
    return errors


def _validate_native_abi_native(cap: str, native: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    library = native.get("library")
    if not isinstance(library, str) or not library.strip():
        errors.append(f"entry.{cap}.native.library is required for native-abi")
    open_symbol = native.get("open_symbol", "frt_model_runtime_open_v1")
    if not isinstance(open_symbol, str) or not open_symbol.replace("_", "a").isalnum():
        errors.append(f"entry.{cap}.native.open_symbol must be a C identifier, got {open_symbol!r}")
    preload = native.get("preload", [])
    if preload and (
        not isinstance(preload, list) or not all(isinstance(p, str) and p for p in preload)
    ):
        errors.append(f"entry.{cap}.native.preload must be an array of strings")
    return errors


def validate_bundle_execution(bundle: BundleManifest) -> list[str]:
    """Return validation errors for ``entry.kind`` and native specs."""
    errors: list[str] = []
    for cap, spec in (("run", bundle.entry_run), ("serve", bundle.entry_serve)):
        if spec is None:
            continue
        if spec.kind not in VALID_ENTRY_KINDS:
            errors.append(
                f"entry.{cap}.kind {spec.kind!r} is not one of "
                f"{sorted(VALID_ENTRY_KINDS)}"
            )
            continue
        if spec.kind == "native-exec":
            errors.extend(_validate_native_exec_native(cap, spec.native))
        elif spec.kind == "native-abi":
            errors.extend(_validate_native_abi_native(cap, spec.native))
    try:
        check_bundle_execution_versions(bundle)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


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
    check_bundle_execution_versions(bundle)


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
    entry_kind = "python"
    entry_native: dict[str, Any] = {}
    if isinstance(entry, dict):
        entry_kind = str(entry.get("kind", "python")).strip().lower() or "python"
        if isinstance(entry.get("native"), dict):
            entry_native = entry["native"]
    entry_run = EntrySpec.from_dict(
        entry.get("run") if isinstance(entry, dict) else None,
        default_kind=entry_kind,
        default_native=entry_native,
    )
    entry_serve = EntrySpec.from_dict(
        entry.get("serve") if isinstance(entry, dict) else None,
        default_kind=entry_kind,
        default_native=entry_native,
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
