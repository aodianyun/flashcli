"""Ensure CUDA userland libs (libcublas / libcudart) for native .so load.

``nvidia-smi`` ``CUDA Version`` is driver capability only. Bundle native artifacts
tagged ``cu130`` need ``libcublas.so.13`` on the dynamic loader path; ``cu124`` /
``cu128`` need ``.so.12``.

CUDA 12 pip wheels use ``site-packages/nvidia/<component>/lib/``.
CUDA 13 consolidated wheels use ``site-packages/nvidia/cu13/lib/``.
``ctypes.CDLL(soname)`` often fails even after setting ``LD_LIBRARY_PATH`` in-process;
probe and preload by absolute path, and always export those dirs for child processes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.runtime.detect import GpuInfo, detect_gpu
from flashcli_bundle.runtime.requirements_spec import venv_purelib
from flashcli_bundle.runtime_env import cuda_runtime_family, parse_variant_key

# cu124/cu128 → CUDA 12.x SONAMEs; cu130 → CUDA 13.x
_SONAMES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "12": ("libcublas.so.12", "libcudart.so.12"),
    "13": ("libcublas.so.13", "libcudart.so.13"),
}

# Prefer loading cublasLt before cublas (dependency order).
_PRELOAD_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "12": ("libcublasLt.so.12", "libcublas.so.12", "libcudart.so.12"),
    "13": ("libcublasLt.so.13", "libcublas.so.13", "libcudart.so.13"),
}

# Pip packages that provide those SONAMEs under site-packages/nvidia/
_PIP_PACKAGES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "12": ("nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12"),
    "13": ("nvidia-cublas>=13,<14", "nvidia-cuda-runtime>=13,<14"),
}


def cuda_sonames_for_tag(cuda_tag: str) -> tuple[str, ...]:
    family = cuda_runtime_family(cuda_tag)
    return _SONAMES_BY_FAMILY.get(family, ())


def cuda_pip_packages_for_tag(cuda_tag: str) -> tuple[str, ...]:
    family = cuda_runtime_family(cuda_tag)
    return _PIP_PACKAGES_BY_FAMILY.get(family, ())


def site_packages_root(python: Path) -> Path | None:
    return venv_purelib(python)


def nvidia_lib_dirs(python: Path) -> list[Path]:
    """Return nvidia lib dirs (legacy ``nvidia/*/lib`` and CUDA 13 ``nvidia/cu13/lib``)."""
    purelib = site_packages_root(python)
    if purelib is None:
        return []
    root = purelib / "nvidia"
    if not root.is_dir():
        return []
    dirs: list[Path] = []
    seen: set[Path] = set()
    # Prefer consolidated cu13/cu12 layout first when present.
    for name in ("cu13", "cu12"):
        lib = root / name / "lib"
        if lib.is_dir():
            resolved = lib.resolve()
            if resolved not in seen:
                dirs.append(resolved)
                seen.add(resolved)
    # Legacy per-component layout: nvidia/cublas/lib, nvidia/cuda_runtime/lib, …
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        lib = child / "lib"
        if lib.is_dir():
            resolved = lib.resolve()
            if resolved not in seen:
                dirs.append(resolved)
                seen.add(resolved)
        # Rare nested: nvidia/<pkg>/lib64
        lib64 = child / "lib64"
        if lib64.is_dir():
            resolved = lib64.resolve()
            if resolved not in seen:
                dirs.append(resolved)
                seen.add(resolved)
    return dirs


def find_soname_file(python: Path, soname: str) -> Path | None:
    """Locate *soname* under the venv's ``nvidia/`` tree (any layout)."""
    purelib = site_packages_root(python)
    if purelib is None:
        return None
    root = purelib / "nvidia"
    if not root.is_dir():
        return None
    # Fast path: known layouts
    for lib_dir in nvidia_lib_dirs(python):
        candidate = lib_dir / soname
        if candidate.is_file():
            return candidate.resolve()
    # Fallback: recursive (handles unexpected nesting)
    matches = sorted(root.rglob(soname))
    for path in matches:
        if path.is_file():
            return path.resolve()
    return None


def prepend_ld_library_path(dirs: list[Path]) -> list[Path]:
    """Prepend *dirs* to ``LD_LIBRARY_PATH``; return dirs that were newly added."""
    if not dirs:
        return []
    existing: list[Path] = []
    for p in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
        if not p.strip():
            continue
        try:
            existing.append(Path(p).resolve())
        except OSError:
            existing.append(Path(p))
    added: list[Path] = []
    for d in reversed(dirs):  # keep *dirs* order at the front
        if d not in existing:
            existing.insert(0, d)
            added.append(d)
    os.environ["LD_LIBRARY_PATH"] = ":".join(str(p) for p in existing)
    return added


def _cdll_path(path: Path) -> bool:
    try:
        import ctypes

        ctypes.CDLL(str(path))
        return True
    except OSError:
        return False


def soname_loadable(soname: str, *, python: Path | None = None) -> bool:
    """True if *soname* can be loaded (absolute path preferred over bare name)."""
    if python is not None:
        path = find_soname_file(python, soname)
        if path is not None and _cdll_path(path):
            return True
        # Subprocess probe with LD_LIBRARY_PATH (matches child native load better).
        if _soname_loadable_in_python(python, soname):
            return True
    try:
        import ctypes

        ctypes.CDLL(soname)
        return True
    except OSError:
        return False


def _soname_loadable_in_python(python: Path, soname: str) -> bool:
    lib_dirs = nvidia_lib_dirs(python)
    env = os.environ.copy()
    if lib_dirs:
        prefix = ":".join(str(d) for d in lib_dirs)
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{prefix}:{prev}" if prev else prefix
    abs_path = find_soname_file(python, soname)
    script = (
        "import ctypes, sys\n"
        f"path = {str(abs_path)!r}\n"
        "try:\n"
        "    ctypes.CDLL(path if path else sys.argv[1])\n"
        "except OSError:\n"
        "    raise SystemExit(1)\n"
    )
    proc = subprocess.run(
        [str(python), "-c", script, soname],
        env=env,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def missing_cuda_sonames(cuda_tag: str, *, python: Path | None = None) -> list[str]:
    return [
        name
        for name in cuda_sonames_for_tag(cuda_tag)
        if not soname_loadable(name, python=python)
    ]


def soname_files_present(cuda_tag: str, *, python: Path) -> bool:
    """True when required SONAME files exist on disk (even if not yet loadable)."""
    return all(
        find_soname_file(python, name) is not None
        for name in cuda_sonames_for_tag(cuda_tag)
    )


def preload_cuda_libs(python: Path, cuda_tag: str) -> None:
    """dlopen absolute paths so subsequent native imports resolve deps."""
    family = cuda_runtime_family(cuda_tag)
    for name in _PRELOAD_BY_FAMILY.get(family, cuda_sonames_for_tag(cuda_tag)):
        path = find_soname_file(python, name)
        if path is not None:
            _cdll_path(path)


def _pip_install(python: Path, packages: tuple[str, ...], *, quiet: bool) -> None:
    # No --upgrade: avoid re-downloading 400MB+ when files already exist but path
    # discovery was wrong; only install when packages/files are missing.
    cmd = [str(python), "-m", "pip", "install", *packages]
    if quiet:
        cmd.append("-q")
    index = os.environ.get("PIP_INDEX_URL", "").strip()
    if index:
        cmd.extend(["-i", index])
        host = os.environ.get("PIP_TRUSTED_HOST", "").strip()
        if host:
            cmd.extend(["--trusted-host", host])
    subprocess.run(cmd, check=True)


def resolve_artifact_cuda_tag(
    bundle: BundleManifest,
    *,
    gpu: GpuInfo | None = None,
) -> str:
    """CUDA tag from the selected bundle runtime cell (not only host nvidia-smi)."""
    from flashcli_bundle.manifest_ext import resolve_bundle_env_key

    gpu = gpu or detect_gpu()
    if gpu is None:
        return "124"
    try:
        env_key = resolve_bundle_env_key(bundle, gpu=gpu)
        tag = parse_variant_key(env_key).cuda_tag
        if tag:
            return tag
    except RuntimeError:
        pass
    return gpu.cuda_tag or "124"


def ensure_cuda_userland_libs(
    *,
    python: Path,
    cuda_tag: str,
    quiet: bool = False,
    install: bool = True,
) -> None:
    """Make libcublas/libcudart for *cuda_tag* loadable in this process.

    1. Prepend venv nvidia lib dirs to ``LD_LIBRARY_PATH``.
    2. If SONAME files are missing and *install*, ``pip install`` matching wheels.
    3. Preload by absolute path; re-probe; raise if still missing.
    """
    skip = os.environ.get("FLASHCLI_SKIP_CUDA_USERLAND", "").strip().lower()
    if skip in ("1", "true", "yes", "on"):
        return

    sonames = cuda_sonames_for_tag(cuda_tag)
    if not sonames:
        return

    prepend_ld_library_path(nvidia_lib_dirs(python))
    missing = missing_cuda_sonames(cuda_tag, python=python)
    if not missing:
        preload_cuda_libs(python, cuda_tag)
        return

    packages = cuda_pip_packages_for_tag(cuda_tag)
    files_ok = soname_files_present(cuda_tag, python=python)
    if files_ok:
        # Files exist (e.g. nvidia/cu13/lib) but bare CDLL failed — path fix only.
        prepend_ld_library_path(nvidia_lib_dirs(python))
        preload_cuda_libs(python, cuda_tag)
        still = missing_cuda_sonames(cuda_tag, python=python)
        if not still:
            if not quiet:
                print(f"[ok] CUDA userland ready for cu{cuda_tag}: {', '.join(sonames)}")
            return
        raise RuntimeError(_missing_msg(cuda_tag, still, python, installed=True))

    if not install or not packages:
        raise RuntimeError(_missing_msg(cuda_tag, missing, python, installed=False))

    if not quiet:
        print(
            f"CUDA userland missing ({', '.join(missing)}) for cu{cuda_tag} — "
            f"installing into bundle venv: {' '.join(packages)}"
        )
    try:
        _pip_install(python, packages, quiet=quiet)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            _missing_msg(cuda_tag, missing, python, installed=False)
            + f"\n  pip install failed (exit {exc.returncode}). "
            "Install CUDA toolkit matching the artifact, or fix network/pip."
        ) from exc

    prepend_ld_library_path(nvidia_lib_dirs(python))
    preload_cuda_libs(python, cuda_tag)
    still = missing_cuda_sonames(cuda_tag, python=python)
    if still:
        raise RuntimeError(_missing_msg(cuda_tag, still, python, installed=True))

    if not quiet:
        print(f"[ok] CUDA userland ready for cu{cuda_tag}: {', '.join(sonames)}")


def ensure_cuda_userland_for_bundle(
    bundle: BundleManifest,
    *,
    python: Path,
    gpu: GpuInfo | None = None,
    quiet: bool = False,
    install: bool = True,
) -> str:
    """Resolve artifact CUDA tag and ensure matching userland libs. Returns cuda_tag."""
    tag = resolve_artifact_cuda_tag(bundle, gpu=gpu)
    ensure_cuda_userland_libs(
        python=python, cuda_tag=tag, quiet=quiet, install=install
    )
    return tag


def _missing_msg(
    cuda_tag: str,
    missing: list[str],
    python: Path,
    *,
    installed: bool,
) -> str:
    family = cuda_runtime_family(cuda_tag)
    toolkit = "13.x" if family == "13" else "12.x"
    libs = ", ".join(missing)
    hint_pip = " ".join(cuda_pip_packages_for_tag(cuda_tag))
    purelib = site_packages_root(python)
    cu_hint = (
        f"{purelib}/nvidia/cu{family}/lib"
        if purelib is not None
        else f"<venv>/lib/python*/site-packages/nvidia/cu{family}/lib"
    )
    lines = [
        f"Missing CUDA userland libraries for native cu{cuda_tag}: {libs}",
        f"  Bundle venv: {python}",
        f"  nvidia-smi 'CUDA Version' is driver capability only — need CUDA {toolkit} libs.",
        f"  Expected pip layout (CUDA {toolkit}): {cu_hint}/",
    ]
    if installed:
        lines.append(
            "  Packages/files may be present but could not be dlopen'd — check deps "
            "(libcublasLt) and LD_LIBRARY_PATH."
        )
        lines.append(f"  Check: ls {cu_hint}/libcublas.so* 2>/dev/null")
    else:
        lines.append(f"  Try: {python} -m pip install {hint_pip}")
    lines.append(
        f"  Or install system CUDA {toolkit} toolkit and export "
        "LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH"
    )
    lines.append("  Skip auto-install: FLASHCLI_SKIP_CUDA_USERLAND=1")
    return "\n".join(lines)
