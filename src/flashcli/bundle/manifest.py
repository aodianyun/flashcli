"""Parse flashcli-model-bundle manifests (format_version 3)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flashcli.runtime.detect import GpuInfo

BUNDLE_FORMAT = "flashcli-model-bundle"
BUNDLE_FORMAT_VERSION = 3


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


def bundle_python_root(bundle: BundleManifest) -> Path:
    """Directory prepended to sys.path for ``entry`` imports."""
    return bundle.bundle_root.resolve()


def bundle_python_abi(bundle: BundleManifest) -> str:
    abi = str(bundle.raw.get("python_abi", "")).strip()
    if not abi or not abi.isdigit() or len(abi) != 3:
        raise ValueError(
            f"Bundle {bundle.name!r} missing valid python_abi (expected e.g. '312')"
        )
    return abi


def _runtime_map_from_raw(raw: dict[str, Any]) -> dict[str, str]:
    """Read env_key → artifact path from ``runtime``."""
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


def bundle_torch_index(
    bundle: BundleManifest,
    *,
    env_key: str | None = None,
    gpu: "GpuInfo | None" = None,
) -> str:
    """Resolve PyTorch wheel index (``cu124`` / ``cu128``) for bundle venv install.

    Manifest ``python_dependencies.torch.index`` may be explicit (``cu124``) or
    ``auto`` / omitted — then index follows the matched runtime env key or GPU.
    """
    from flashcli.bundle.runtime_env import parse_variant_key
    from flashcli.runtime.detect import GpuInfo, detect_gpu, torch_index_for_cuda_tag
    from flashcli.runtime.requirements_spec import parse_torch_dependency

    py = bundle.raw.get("python_dependencies")
    idx = ""
    if isinstance(py, dict):
        _, idx = parse_torch_dependency(py.get("torch", "torch"))

    if idx and idx.lower() != "auto":
        return idx

    if env_key:
        try:
            return torch_index_for_cuda_tag(parse_variant_key(env_key).cuda_tag)
        except ValueError:
            pass

    gpu = gpu or detect_gpu()
    if gpu is not None:
        return gpu.recommended_torch_index
    return "cu124"


def bundle_runtime_dir(bundle: BundleManifest, env_key: str) -> Path:
    """Absolute path to ``runtime/<env-key>/`` (or manifest path) for one cell."""
    runtime_map = bundle_runtime_map(bundle)
    rel = str(runtime_map.get(env_key, "")).strip().lstrip("/")
    if not rel:
        raise ValueError(
            f"Bundle {bundle.name!r} has no runtime path for env {env_key!r}"
        )
    return (bundle.bundle_root / rel).resolve()


def resolve_bundle_env_key(
    bundle: BundleManifest,
    *,
    gpu: "GpuInfo | None" = None,
) -> str:
    """Match host GPU/CUDA/Python to a key in manifest ``runtime``."""
    from flashcli.bundle.runtime_env import resolve_runtime_env_key, variant_dir_name
    from flashcli.runtime.detect import detect_gpu_or_raise

    gpu = gpu or detect_gpu_or_raise()
    python_abi = bundle_python_abi(bundle)
    host_key = variant_dir_name(gpu, python_minor=python_abi)
    env_key = resolve_runtime_env_key(bundle_runtime_map(bundle), host_key)
    if env_key is None:
        matrix = bundle_runtime_matrix(bundle)
        raise RuntimeError(
            f"Bundle {bundle.name!r} does not support runtime environment {host_key!r}. "
            f"Supported: {', '.join(matrix)}"
        )
    return env_key


def bundle_active_native_dir(
    bundle: BundleManifest,
    *,
    gpu: "GpuInfo | None" = None,
    env_key: str | None = None,
) -> Path:
    """Native ``.so`` directory for this host (single ``runtime/<env-key>/``)."""
    if env_key is None:
        env_key = resolve_bundle_env_key(bundle, gpu=gpu)
    return bundle_runtime_dir(bundle, env_key)


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
    entry = data.get("entry") or {}
    entry_run = EntrySpec.from_dict(entry.get("run") if isinstance(entry, dict) else None)
    entry_serve = EntrySpec.from_dict(
        entry.get("serve") if isinstance(entry, dict) else None
    )
    manifest = BundleManifest(
        bundle_root=root,
        name=str(data.get("name", root.name)),
        capabilities=_capabilities_from_data(entry_run, entry_serve),
        entry_run=entry_run,
        entry_serve=entry_serve,
        description=str(data.get("description", "")),
        raw=data,
    )
    require_v3(manifest)
    return manifest


def load_bundle_manifest_data(data: dict[str, Any], *, bundle_root: Path) -> BundleManifest:
    entry = data.get("entry") or {}
    entry_run = EntrySpec.from_dict(entry.get("run") if isinstance(entry, dict) else None)
    entry_serve = EntrySpec.from_dict(entry.get("serve") if isinstance(entry, dict) else None)
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


def _entry_module_path(bundle: BundleManifest, spec: EntrySpec) -> Path | None:
    parts = spec.module.split(".")
    if not parts:
        return None
    py_root = bundle_python_root(bundle)
    return py_root.joinpath(*parts[:-1], f"{parts[-1]}.py")


def validate_bundle_layout(
    bundle: BundleManifest,
    *,
    probe_abi: bool = False,
    env_key: str | None = None,
) -> list[str]:
    """Return validation errors (empty if OK)."""
    errors: list[str] = []
    py_root = bundle_python_root(bundle)

    try:
        require_v3(bundle)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    if not isinstance(bundle.raw.get("python_dependencies"), dict):
        errors.append("flashcli-bundle.json missing python_dependencies")

    try:
        abi = bundle_python_abi(bundle)
        matrix = bundle_runtime_matrix(bundle)
        for cell in matrix:
            if not cell.endswith(f"-py{abi}"):
                errors.append(
                    f"runtime key {cell!r} does not match python_abi={abi!r}"
                )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        bundle_runtime_map(bundle)
    except ValueError as exc:
        errors.append(str(exc))

    for cap, spec in (
        ("run", bundle.entry_run),
        ("serve", bundle.entry_serve),
    ):
        if spec is None:
            continue
        mod_path = _entry_module_path(bundle, spec)
        if mod_path is None or not mod_path.is_file():
            errors.append(
                f"entry.{cap} module file not found: {mod_path} "
                f"(module {spec.module!r} under {py_root})"
            )

    from flashcli.bundle.native_validate import validate_native_runtime
    from flashcli.bundle.weights import validate_weights_spec
    from flashcli.bundle.bundle_options import validate_bundle_options

    errors.extend(validate_native_runtime(bundle, probe_abi=probe_abi, env_key=env_key))
    errors.extend(validate_weights_spec(bundle))
    errors.extend(validate_bundle_options(bundle))

    if not (bundle.bundle_root / "flash_rt").is_dir():
        errors.append("missing flash_rt/ Python tree")

    return errors


def check_bundle_python_abi(bundle: BundleManifest) -> None:
    """Raise if the running interpreter does not match bundle ``python_abi``."""
    abi = bundle_python_abi(bundle)
    host = f"{sys.version_info.major}{sys.version_info.minor:02d}"
    if abi != host:
        major, minor = int(abi[0]), int(abi[1:])
        raise RuntimeError(
            f"Python ABI mismatch for bundle {bundle.name!r}: "
            f"interpreter is 3.{host[1:]} ({sys.executable}), "
            f"but bundle requires python_abi={abi!r} (Python 3.{minor}). "
            f"flashcli should re-exec into the bundle venv automatically; "
            f"if this persists, recreate the bundle runtime venv."
        )
