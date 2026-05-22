"""GPU detection and runtime manifest parsing (model bundles only)."""

from flashcli.runtime.detect import (
    GpuInfo,
    detect_gpu,
    detect_gpu_or_raise,
    torch_index_for_cuda_tag,
)

__all__ = [
    "GpuInfo",
    "detect_gpu",
    "detect_gpu_or_raise",
    "torch_index_for_cuda_tag",
]
