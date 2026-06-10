"""Preflight checks before downloading bundle artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from flashcli.bundle.manifest import (
    BundleManifest,
    bundle_runtime_map,
    bundle_runtime_matrix,
    bundle_python_abi,
)
from flashcli.bundle.python_install import ensure_python_for_minor
from flashcli.bundle.runtime_env import resolve_runtime_env_key, variant_dir_name
from flashcli.runtime.detect import GpuInfo, detect_gpu_or_raise


class BundleEnvironmentError(RuntimeError):
    exit_code = 2


@dataclass(frozen=True)
class PreflightResult:
    env_key: str
    host_env_key: str
    python_abi: str
    python_path: str
    manifest: BundleManifest


def host_env_key(gpu: GpuInfo, python_abi: str) -> str:
    return variant_dir_name(gpu, python_minor=python_abi)


def run_preflight(
    manifest: BundleManifest,
    *,
    gpu: GpuInfo | None = None,
) -> PreflightResult:
    """Validate GPU/CUDA/SM/Python support before artifact download."""
    gpu = gpu or detect_gpu_or_raise()
    python_abi = bundle_python_abi(manifest)
    host_key = host_env_key(gpu, python_abi)
    runtime_map = bundle_runtime_map(manifest)
    matrix = bundle_runtime_matrix(manifest)
    env_key = resolve_runtime_env_key(runtime_map, host_key)

    if env_key is None:
        raise BundleEnvironmentError(
            f"Bundle {manifest.name!r} does not support this machine's runtime "
            f"environment {host_key!r}.\n"
            f"  GPU: {gpu.gpu_name or 'NVIDIA GPU'} (sm{gpu.sm}, cuda_tag={gpu.cuda_tag})\n"
            f"  Bundle python_abi: {python_abi} (Python 3.{python_abi[1:]})\n"
            f"  Supported runtime environments ({len(matrix)}):\n"
            + "".join(f"    - {c}\n" for c in matrix)
            + "\n  Fix: use a supported GPU/CUDA stack, or publish/download a bundle "
            "build that includes your environment."
        )

    try:
        py = ensure_python_for_minor(python_abi)
    except RuntimeError as exc:
        raise BundleEnvironmentError(str(exc)) from exc
    if py is None:
        major, minor = int(python_abi[0]), int(python_abi[1:])
        raise BundleEnvironmentError(
            f"Cannot provision Python 3.{minor} for bundle {manifest.name!r} "
            f"(python_abi={python_abi}).\n"
            f"  Auto-install is disabled (FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON=0).\n"
            f"  Install python{major}.{minor}, set "
            f"FLASHCLI_PY{python_abi}_BIN=/path/to/python{major}.{minor}, "
            f"or re-enable auto-install."
        )

    return PreflightResult(
        env_key=env_key,
        host_env_key=host_key,
        python_abi=python_abi,
        python_path=str(py),
        manifest=manifest,
    )
