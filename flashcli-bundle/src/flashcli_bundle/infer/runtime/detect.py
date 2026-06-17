"""GPU and platform detection for runtime / torch index selection."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass


def _cuda_tag_from_env() -> str | None:
    raw = os.environ.get("FLASHCLI_CUDA_TAG", "").strip().lstrip("cCuU")
    return raw or None


@dataclass(frozen=True)
class GpuInfo:
    sm: str
    cuda_tag: str
    os_name: str
    arch: str
    recommended_torch_index: str
    driver_version: str | None = None
    gpu_name: str | None = None


def _parse_sm(compute_cap: str) -> str:
    """e.g. '8.9' -> '89', '12.0' -> '120'."""
    parts = compute_cap.strip().split(".")
    if len(parts) == 2:
        return f"{int(parts[0])}{int(parts[1])}"
    return compute_cap.replace(".", "")


def torch_index_for_cuda_tag(cuda_tag: str) -> str:
    """Map runtime manifest ``cuda_tag`` to PyTorch wheel index name."""
    if cuda_tag in ("128", "130"):
        return "cu128"
    return "cu124"


def detect_cuda_tag_from_nvidia_smi() -> str | None:
    """Map driver-reported max CUDA (nvidia-smi banner) to runtime cuda_tag."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"CUDA Version:\s*([0-9]+)\.([0-9]+)", out.stdout)
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    if major >= 13:
        return "130"
    if major == 12:
        if minor >= 8:
            return "128"
        if minor >= 4:
            return "124"
        return "120"
    return None


def detect_cuda_tag_from_nvcc() -> str | None:
    """Map installed CUDA toolkit (nvcc) to runtime package cuda_tag (124/128/130)."""
    if shutil.which("nvcc") is None:
        return None
    try:
        out = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"release\s+([0-9]+)\.([0-9]+)", out.stdout)
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    ver = f"{major}.{minor}"
    if ver in ("12.4", "12.5", "12.6"):
        return "124"
    if ver in ("12.8", "12.9"):
        return "128"
    if major >= 13:
        return "130"
    tag = f"{major}{minor}"
    return tag[:3]


def detect_gpu() -> GpuInfo | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,compute_cap,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
        return None
    name = parts[0]
    compute_cap = parts[1]
    driver = parts[2] if len(parts) > 2 else None
    sm = _parse_sm(compute_cap)
    cuda_tag = _cuda_tag_from_env()
    if cuda_tag is None:
        cuda_tag = detect_cuda_tag_from_nvcc()
    if cuda_tag is None:
        cuda_tag = detect_cuda_tag_from_nvidia_smi()
    if cuda_tag is None:
        cuda_tag = "128" if sm in ("120", "110") else "124"
    arch = platform.machine()
    if arch == "aarch64":
        arch = "aarch64"
    elif arch in ("x86_64", "AMD64"):
        arch = "x86_64"
    return GpuInfo(
        sm=sm,
        cuda_tag=cuda_tag,
        os_name=platform.system().lower(),
        arch=arch,
        recommended_torch_index=torch_index_for_cuda_tag(cuda_tag),
        driver_version=driver,
        gpu_name=name,
    )


def detect_gpu_or_raise() -> GpuInfo:
    info = detect_gpu()
    if info is None:
        raise RuntimeError(
            "No NVIDIA GPU detected (nvidia-smi unavailable). "
            "Model bundles require a CUDA GPU for inference."
        )
    if info.os_name != "linux":
        raise RuntimeError(
            f"Unsupported OS for flashcli: {info.os_name!r} "
            "(v1 targets linux only)."
        )
    return info


def torch_index_url(index_name: str) -> str:
    name = index_name if index_name.startswith("cu") else f"cu{index_name}"
    return f"https://download.pytorch.org/whl/{name}"
