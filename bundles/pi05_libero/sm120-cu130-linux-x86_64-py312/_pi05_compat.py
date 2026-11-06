"""Pi0.5 bundle-local compat (SM89 .so without fp8_nt_dev). Not part of flashcli core."""

from __future__ import annotations

import warnings
from typing import Any, Callable

_GEMM_PREFERRED = ("fp8_nt_dev", "autotune_fp8_nt_dev")
_GEMM_FALLBACK = "fp8_run_dev"


def _install_gemm_shims(gemm_cls: type) -> list[str]:
    installed: list[str] = []
    if not hasattr(gemm_cls, _GEMM_FALLBACK):
        return installed

    run_dev: Callable[..., Any] = gemm_cls.fp8_run_dev  # type: ignore[attr-defined]

    if not hasattr(gemm_cls, "fp8_nt_dev"):

        def fp8_nt_dev(
            self: Any,
            A: int,
            B: int,
            D: int,
            M: int,
            N: int,
            K: int,
            d_scale_a: int,
            d_scale_b: int,
            stream: int = 0,
        ) -> None:
            run_dev(self, A, B, D, M, N, K, d_scale_a, d_scale_b, stream)

        gemm_cls.fp8_nt_dev = fp8_nt_dev  # type: ignore[attr-defined]
        installed.append("fp8_nt_dev")

    if not hasattr(gemm_cls, "autotune_fp8_nt_dev"):

        def autotune_fp8_nt_dev(
            self: Any,
            A: int,
            B: int,
            D: int,
            M: int,
            N: int,
            K: int,
            d_scale_a: int,
            d_scale_b: int,
            num_algos: int = 16,
        ) -> None:
            del num_algos
            run_dev(self, A, B, D, M, N, K, d_scale_a, d_scale_b, 0)

        gemm_cls.autotune_fp8_nt_dev = autotune_fp8_nt_dev  # type: ignore[attr-defined]
        installed.append("autotune_fp8_nt_dev")

    return installed


def prepare_flash_rt_kernels(*, quiet: bool = False) -> list[str]:
    """Import bundle ``flash_rt_kernels`` once and patch GemmRunner if needed."""
    from flash_rt import flash_rt_kernels as fvk  # noqa: PLC0415

    gemm_cls = fvk.GemmRunner
    missing = [n for n in _GEMM_PREFERRED if not hasattr(gemm_cls, n)]
    if not missing:
        return []
    if not hasattr(gemm_cls, _GEMM_FALLBACK):
        raise RuntimeError(
            "flash_rt_kernels.so lacks Pi0.5 FP8 support "
            f"(missing {', '.join(missing)} and {_GEMM_FALLBACK!r}). "
            "Rebuild bundle: bash bundles/pi05_libero/build.sh --repo-root /path/to/FlashRT"
        )
    installed = _install_gemm_shims(gemm_cls)
    if not quiet and installed:
        warnings.warn(
            "pi05_libero: GemmRunner missing "
            + ", ".join(missing)
            + f"; using {_GEMM_FALLBACK!r} shims ("
            + ", ".join(installed)
            + "). Rebuild FlashRT .so for native fp8_nt_dev.",
            stacklevel=2,
        )
    still = [n for n in _GEMM_PREFERRED if not hasattr(gemm_cls, n)]
    if still:
        raise RuntimeError(f"GemmRunner shims failed: still missing {still}")
    return installed
