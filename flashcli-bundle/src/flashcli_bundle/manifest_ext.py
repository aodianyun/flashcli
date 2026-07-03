"""Parse flashcli-model-bundle manifests (format_version 3)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flashcli_bundle.manifest import (
    BUNDLE_FORMAT,
    BUNDLE_FORMAT_VERSION,
    BundleManifest,
    EntrySpec,
    bundle_format_version,
    bundle_python_abi,
    bundle_python_root,
    bundle_runtime_dir,
    bundle_runtime_map,
    bundle_runtime_matrix,
    load_bundle_manifest,
    load_bundle_manifest_data,
    require_v3,
)

if TYPE_CHECKING:
    from flashcli_bundle.native_validate import PythonForMinorFn
    from flashcli_bundle.runtime.detect import GpuInfo

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_FORMAT_VERSION",
    "BundleManifest",
    "EntrySpec",
    "bundle_format_version",
    "bundle_python_abi",
    "bundle_python_root",
    "bundle_runtime_dir",
    "bundle_runtime_map",
    "bundle_runtime_matrix",
    "load_bundle_manifest",
    "load_bundle_manifest_data",
    "require_v3",
    "bundle_torch_index",
    "resolve_bundle_env_key",
    "bundle_active_native_dir",
    "validate_bundle_layout",
    "check_bundle_python_abi",
]


def bundle_torch_index(
    bundle: BundleManifest,
    *,
    env_key: str | None = None,
    gpu: "GpuInfo | None" = None,
) -> str:
    from flashcli_bundle.runtime_env import parse_variant_key
    from flashcli_bundle.runtime.detect import GpuInfo, detect_gpu, torch_index_for_cuda_tag
    from flashcli_bundle.runtime.requirements_spec import parse_torch_dependency

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


def resolve_bundle_env_key(
    bundle: BundleManifest,
    *,
    gpu: "GpuInfo | None" = None,
) -> str:
    from flashcli_bundle.runtime_env import resolve_runtime_env_key, variant_dir_name
    from flashcli_bundle.runtime.detect import detect_gpu_or_raise

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
    if env_key is None:
        env_key = resolve_bundle_env_key(bundle, gpu=gpu)
    return bundle_runtime_dir(bundle, env_key)


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
    python_for_minor: PythonForMinorFn | None = None,
) -> list[str]:
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
        entry_raw = (bundle.raw.get("entry") or {}).get(cap)
        if isinstance(entry_raw, dict):
            raw_mode = str(entry_raw.get("mode", "engine")).strip().lower() or "engine"
            if raw_mode not in ("engine", "script"):
                errors.append(
                    f"entry.{cap}.mode must be 'engine' or 'script', got {raw_mode!r}"
                )
        mod_path = _entry_module_path(bundle, spec)
        if mod_path is None or not mod_path.is_file():
            errors.append(
                f"entry.{cap} module file not found: {mod_path} "
                f"(module {spec.module!r} under {py_root})"
            )

    from flashcli_bundle.native_validate import validate_native_runtime
    from flashcli_bundle.weights_spec import validate_weights_spec
    from flashcli_bundle.manifest import validate_bundle_protocol_version
    from flashcli_bundle.options import validate_bundle_options

    errors.extend(
        validate_native_runtime(
            bundle,
            probe_abi=probe_abi,
            env_key=env_key,
            python_for_minor=python_for_minor,
        )
    )
    errors.extend(validate_weights_spec(bundle))
    errors.extend(validate_bundle_options(bundle))
    errors.extend(validate_bundle_protocol_version(bundle))

    if not (bundle.bundle_root / "flash_rt").is_dir():
        errors.append("missing flash_rt/ Python tree")

    if bundle.name == "groot_n17":
        vendor_meta = bundle.bundle_root / "gr00t" / "VENDOR.json"
        if not vendor_meta.is_file():
            errors.append(
                "missing vendored gr00t/ (run bundles/groot_n17/vendor_gr00t.sh or build.sh)"
            )

    return errors


def check_bundle_python_abi(bundle: BundleManifest) -> None:
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
