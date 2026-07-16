"""Host ABI gate from selected native ``.so`` files (no manifest config).

Reads ``GLIBC_*`` / ``GLIBCXX_*`` (and ``CXXABI_*``) version needs from the
matched runtime cell artifacts via ``readelf -V`` / ``objdump -p``, compares
against the host ``libc`` / ``libstdc++``, then probes load in the bundle venv.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flashcli_bundle.errors import NativeHostAbiError
from flashcli_bundle.manifest import BundleManifest
from flashcli_bundle.manifest_ext import bundle_active_native_dir, resolve_bundle_env_key
from flashcli_bundle.native_naming import discover_native_module_bases, select_native_module_ranked
from flashcli_bundle.runtime.detect import GpuInfo, detect_gpu, detect_gpu_or_raise

_GLIBC_RE = re.compile(r"\bGLIBC_([0-9]+(?:\.[0-9]+)*)\b")
_GLIBCXX_RE = re.compile(r"\bGLIBCXX_([0-9]+(?:\.[0-9]+)*)\b")
_CXXABI_RE = re.compile(r"\bCXXABI_([0-9]+(?:\.[0-9]+)*)\b")

@dataclass(frozen=True)
class HostAbiRequirements:
    """Maximum versioned symbol requirements extracted from one or more ``.so`` files."""

    glibc: str | None = None
    glibcxx: str | None = None
    cxxabi: str | None = None
    sources: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return self.glibc is None and self.glibcxx is None and self.cxxabi is None


@dataclass(frozen=True)
class HostAbiProvides:
    glibc: str | None = None
    glibcxx: str | None = None
    cxxabi: str | None = None
    libc_path: str | None = None
    libstdcxx_path: str | None = None


def parse_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in version.split("."):
        if not p.isdigit():
            break
        parts.append(int(p))
    return tuple(parts) if parts else (0,)


def version_at_least(have: str | None, need: str | None) -> bool:
    if need is None:
        return True
    if have is None:
        return False
    return parse_version_tuple(have) >= parse_version_tuple(need)


def max_version(*versions: str | None) -> str | None:
    best: str | None = None
    for v in versions:
        if v is None:
            continue
        if best is None or parse_version_tuple(v) > parse_version_tuple(best):
            best = v
    return best


def parse_elf_version_text(text: str) -> HostAbiRequirements:
    """Parse ``readelf -V`` / ``objdump -p`` text into max version needs."""
    glibc_vers = [m.group(1) for m in _GLIBC_RE.finditer(text)]
    glibcxx_vers = [m.group(1) for m in _GLIBCXX_RE.finditer(text)]
    cxxabi_vers = [m.group(1) for m in _CXXABI_RE.finditer(text)]
    return HostAbiRequirements(
        glibc=max_version(*glibc_vers) if glibc_vers else None,
        glibcxx=max_version(*glibcxx_vers) if glibcxx_vers else None,
        cxxabi=max_version(*cxxabi_vers) if cxxabi_vers else None,
    )

def _run_tool(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return None
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def elf_version_text(so: Path) -> str | None:
    """Return version-section dump for *so*, or None if no tool works."""
    if shutil.which("readelf"):
        out = _run_tool(["readelf", "-V", str(so)])
        if out and ("GLIBC_" in out or "GLIBCXX_" in out or "Version" in out):
            return out
    if shutil.which("objdump"):
        out = _run_tool(["objdump", "-p", str(so)])
        if out and ("GLIBC_" in out or "GLIBCXX_" in out or "Version" in out):
            return out
    return None


def elf_version_requirements(so: Path) -> HostAbiRequirements:
    text = elf_version_text(so)
    if not text:
        return HostAbiRequirements(sources=(so.name,))
    req = parse_elf_version_text(text)
    return HostAbiRequirements(
        glibc=req.glibc,
        glibcxx=req.glibcxx,
        cxxabi=req.cxxabi,
        sources=(so.name,),
    )


def merge_requirements(*reqs: HostAbiRequirements) -> HostAbiRequirements:
    sources: list[str] = []
    glibc = glibcxx = cxxabi = None
    for r in reqs:
        sources.extend(r.sources)
        glibc = max_version(glibc, r.glibc)
        glibcxx = max_version(glibcxx, r.glibcxx)
        cxxabi = max_version(cxxabi, r.cxxabi)
    return HostAbiRequirements(
        glibc=glibc,
        glibcxx=glibcxx,
        cxxabi=cxxabi,
        sources=tuple(sources),
    )


def _find_lib(name: str) -> Path | None:
    """Locate a shared library on the host (ldconfig / common paths)."""
    if shutil.which("ldconfig"):
        try:
            proc = subprocess.run(
                ["ldconfig", "-p"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            for line in proc.stdout.splitlines():
                # ldconfig -p: "libstdc++.so.6 (libc6,x86-64) => /path"
                if name not in line or "=>" not in line:
                    continue
                path_s = line.split("=>", 1)[1].strip()
                p = Path(path_s)
                if p.is_file():
                    return p.resolve()
    for candidate in (
        Path(f"/lib/x86_64-linux-gnu/{name}"),
        Path(f"/usr/lib/x86_64-linux-gnu/{name}"),
        Path(f"/lib64/{name}"),
        Path(f"/usr/lib64/{name}"),
        Path(f"/lib/{name}"),
        Path(f"/usr/lib/{name}"),
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _versions_from_lib_file(path: Path, prefix: str) -> str | None:
    """Highest ``PREFIX_x.y`` string found in *path* (via ``strings`` or raw scan)."""
    rx = re.compile(rf"\b{re.escape(prefix)}_([0-9]+(?:\.[0-9]+)*)\b")
    text = ""
    if shutil.which("strings"):
        out = _run_tool(["strings", "-a", str(path)])
        if out:
            text = out
    if not text:
        try:
            # Bound read: version strings are early; 4 MiB is enough for libc/libstdc++.
            data = path.read_bytes()[: 4 * 1024 * 1024]
            text = data.decode("latin-1", errors="ignore")
        except OSError:
            return None
    best: str | None = None
    for m in rx.finditer(text):
        best = max_version(best, m.group(1))
    return best


def host_version_provides() -> HostAbiProvides:
    libc = _find_lib("libc.so.6")
    libstdcxx = _find_lib("libstdc++.so.6")
    glibc = _versions_from_lib_file(libc, "GLIBC") if libc else None
    glibcxx = _versions_from_lib_file(libstdcxx, "GLIBCXX") if libstdcxx else None
    cxxabi = _versions_from_lib_file(libstdcxx, "CXXABI") if libstdcxx else None
    return HostAbiProvides(
        glibc=glibc,
        glibcxx=glibcxx,
        cxxabi=cxxabi,
        libc_path=str(libc) if libc else None,
        libstdcxx_path=str(libstdcxx) if libstdcxx else None,
    )


def compare_abi(needs: HostAbiRequirements, host: HostAbiProvides) -> list[str]:
    """Return human-readable mismatch lines (empty if host satisfies *needs*)."""
    errors: list[str] = []
    src = ", ".join(needs.sources) if needs.sources else "native .so"
    if needs.glibc and not version_at_least(host.glibc, needs.glibc):
        have = host.glibc or "unknown"
        errors.append(
            f"host glibc too old for {src}: need GLIBC_{needs.glibc}, "
            f"host provides GLIBC_{have}"
            + (f" ({host.libc_path})" if host.libc_path else "")
        )
    if needs.glibcxx and not version_at_least(host.glibcxx, needs.glibcxx):
        have = host.glibcxx or "unknown"
        errors.append(
            f"host libstdc++ too old for {src}: need GLIBCXX_{needs.glibcxx}, "
            f"host provides GLIBCXX_{have}"
            + (f" ({host.libstdcxx_path})" if host.libstdcxx_path else "")
        )
    if needs.cxxabi and not version_at_least(host.cxxabi, needs.cxxabi):
        have = host.cxxabi or "unknown"
        errors.append(
            f"host libstdc++ CXXABI too old for {src}: need CXXABI_{needs.cxxabi}, "
            f"host provides CXXABI_{have}"
            + (f" ({host.libstdcxx_path})" if host.libstdcxx_path else "")
        )
    return errors


def host_abi_fix_hints(*, glibc_mismatch: bool = False, libstdcxx_mismatch: bool = False) -> str:
    """Actionable fixes; avoid suggesting g++-13 when glibc itself is too old."""
    lines = ["  Fix (pick one):"]
    if glibc_mismatch:
        lines.append(
            "    - Use Ubuntu 24.04+ (or equivalent) / a newer GPU container "
            "(e.g. nvcr.io/nvidia/pytorch) — glibc cannot be upgraded in place on this host"
        )
    elif libstdcxx_mismatch:
        lines.append(
            "    - Ubuntu 22.04: sudo apt-get install -y g++-13 && "
            "export LD_LIBRARY_PATH=/usr/lib/gcc/x86_64-linux-gnu/13:$LD_LIBRARY_PATH"
        )
        lines.append(
            "    - Or upgrade to Ubuntu 24.04+ / run flashcli in a newer GPU container "
            "(e.g. nvcr.io/nvidia/pytorch)"
        )
    else:
        lines.append(
            "    - Upgrade OS libstdc++/glibc, or run flashcli in a newer GPU container "
            "(e.g. nvcr.io/nvidia/pytorch)"
        )
    lines.append("  Skip this check (debug only): FLASHCLI_SKIP_NATIVE_HOST_ABI=1")
    return "\n".join(lines)


def selected_native_so_paths(
    bundle: BundleManifest,
    *,
    gpu: GpuInfo | None = None,
) -> list[Path]:
    """Paths of native modules selected for this host's runtime cell."""
    gpu = gpu or detect_gpu_or_raise()
    env_key = resolve_bundle_env_key(bundle, gpu=gpu)
    native_dir = bundle_active_native_dir(bundle, gpu=gpu, env_key=env_key)
    from flashcli_bundle.manifest_ext import bundle_python_abi

    python_minor = bundle_python_abi(bundle)
    bases = discover_native_module_bases(native_dir, env_key=env_key)
    paths: list[Path] = []
    for base in bases:
        ranked = select_native_module_ranked(
            native_dir,
            base,
            gpu,
            python_minor=python_minor,
            env_key=env_key,
        )
        if ranked:
            paths.append(ranked[0])
    if not paths and native_dir.is_dir():
        paths = sorted(native_dir.glob("*.so"))
    return paths


def requirements_for_sos(paths: list[Path]) -> HostAbiRequirements:
    return merge_requirements(*(elf_version_requirements(p) for p in paths))


def _probe_load_host_abi(python: Path, so: Path) -> str | None:
    """Return error string if dlopen fails for host ABI (GLIBC/GLIBCXX); else None.

    CUDA-only failures are ignored here (handled by cuda_userland).
    """
    from flashcli_bundle.native_validate import _classify_probe_failure

    script = (
        "import importlib.util, sys\n"
        "path = sys.argv[1]\n"
        "spec = importlib.util.spec_from_file_location('_flashcli_host_abi', path)\n"
        "if spec is None or spec.loader is None:\n"
        "    raise SystemExit('no spec')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "try:\n"
        "    spec.loader.exec_module(mod)\n"
        "except ImportError as exc:\n"
        "    print(exc, file=sys.stderr)\n"
        "    raise SystemExit(1) from exc\n"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", script, str(so.resolve())],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{so.name}: cannot probe load ({exc})"
    if proc.returncode == 0:
        return None
    kind = _classify_probe_failure(proc.stderr or "", proc.stdout or "")
    detail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")[:300]
    if kind == "host_abi":
        return f"{so.name}: {detail}"
    if kind == "cuda_runtime":
        return None
    if kind in ("abi_mismatch", "invalid_elf"):
        return f"{so.name}: {detail}"
    # Unknown load failure after CUDA userland — surface it (may still be host ABI).
    if "GLIBC" in detail or "GLIBCXX" in detail or "CXXABI" in detail:
        return f"{so.name}: {detail}"
    return None


def ensure_native_host_abi_for_bundle(
    bundle: BundleManifest,
    *,
    python: Path,
    gpu: GpuInfo | None = None,
    quiet: bool = False,
) -> None:
    """Fail if the host cannot satisfy ABI needs of the selected native ``.so`` files."""
    skip = os.environ.get("FLASHCLI_SKIP_NATIVE_HOST_ABI", "").strip().lower()
    if skip in ("1", "true", "yes", "on"):
        return

    gpu = gpu or detect_gpu()
    if gpu is None:
        return

    paths = selected_native_so_paths(bundle, gpu=gpu)
    if not paths:
        return

    needs = requirements_for_sos(paths)
    host = host_version_provides()
    mismatches = compare_abi(needs, host)
    if mismatches:
        joined = "\n".join(mismatches)
        lines = [
            "Host system libraries are too old for this bundle's native runtime:",
            *[f"  - {m}" for m in mismatches],
            host_abi_fix_hints(
                glibc_mismatch="glibc too old" in joined,
                libstdcxx_mismatch="libstdc++" in joined,
            ),
        ]
        raise NativeHostAbiError("\n".join(lines))

    # Second line of defense: actual dlopen (catches cases ELF tools missed).
    load_errors: list[str] = []
    for so in paths:
        err = _probe_load_host_abi(python, so)
        if err:
            load_errors.append(err)
    if load_errors:
        joined = "\n".join(load_errors)
        lines = [
            "Host cannot load this bundle's native runtime (.so ABI mismatch):",
            *[f"  - {e}" for e in load_errors],
            host_abi_fix_hints(
                glibc_mismatch="GLIBC" in joined,
                libstdcxx_mismatch="GLIBCXX" in joined or "CXXABI" in joined,
            ),
        ]
        raise NativeHostAbiError("\n".join(lines))

    if not quiet:
        parts: list[str] = []
        if needs.glibc:
            parts.append(f"glibc>={needs.glibc}")
        if needs.glibcxx:
            parts.append(f"GLIBCXX_>={needs.glibcxx}")
        detail = ", ".join(parts) if parts else "ok"
        print(f"[ok] native host ABI ({detail}) for {len(paths)} selected .so")
