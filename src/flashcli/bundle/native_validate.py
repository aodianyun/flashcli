"""Validate ``lib/`` native matrix completeness and Python ABI vs filename tags."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from flashcli.bundle.manifest import BundleManifest, bundle_modules, bundle_native_lib_rel
from flashcli.bundle.native_naming import (
    NATIVE_MODULE_BASES,
    ParsedNativeTag,
    bundle_native_lib_dir,
    bundle_uses_native_matrix,
    list_native_artifacts,
    logical_native_module_name,
    parse_native_tag_from_filename,
)
from flashcli.bundle.runtime_env import host_python_minor

_ABI_MISMATCH_MARKERS = (
    "Python version mismatch",
    "interpreter version is incompatible",
    "Module use count",
    "undefined symbol: Py",
)
_CUDA_LOAD_MARKERS = ("libcublas", "libcudart", "libcuda", "cannot open shared object")
_ELF_BAD_MARKERS = ("invalid ELF", "not an ELF", "Exec format error")

_PROBE_SCRIPT = """
import importlib.util
import sys

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("flashcli_native_probe", path)
if spec is None or spec.loader is None:
    raise SystemExit("cannot create extension spec")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
"""


def _required_module_bases(bundle: BundleManifest, lib_dir: Path) -> tuple[str, ...]:
    """Modules that must exist for every matrix cell."""
    bases: list[str] = ["flash_rt_kernels", "flash_rt_fa2"]
    optional_fp4 = True
    for entry in bundle_modules(bundle):
        file_rel = str(entry.get("file", "")).strip()
        if file_rel.startswith("lib/flash_rt_fp4") and not entry.get("optional"):
            optional_fp4 = False
            break
    if not optional_fp4 or any(lib_dir.glob("flash_rt_fp4*.so")):
        if "flash_rt_fp4" not in bases:
            bases.append("flash_rt_fp4")
    # SM120 Qwen: NVFP4 is inside kernels; do not require flash_rt_fp4.so.
    requires = bundle.raw.get("requires")
    sm_list: list[str] = []
    if isinstance(requires, dict) and isinstance(requires.get("sm"), list):
        sm_list = [str(s).strip() for s in requires["sm"] if str(s).strip()]
    if sm_list == ["120"] and not any(lib_dir.glob("flash_rt_fp4*.so")):
        bases = [b for b in bases if b != "flash_rt_fp4"]
    return tuple(bases)


def _expected_matrix_cells(bundle: BundleManifest, lib_dir: Path) -> set[str]:
    nm = bundle.raw.get("native_matrix")
    if isinstance(nm, list) and nm:
        return {str(x).strip() for x in nm if str(x).strip()}
    arts = list_native_artifacts(lib_dir)
    return {parsed.catalog_key() for parsed, _ in arts.get("flash_rt_kernels", [])}


def _cells_present_in_lib(lib_dir: Path) -> set[str]:
    arts = list_native_artifacts(lib_dir)
    cells: set[str] = set()
    for base in ("flash_rt_kernels", "flash_rt_fa2", "flash_rt_fp4"):
        for parsed, _ in arts.get(base, []):
            cells.add(parsed.catalog_key())
    return cells


def _find_artifact(
    arts: dict[str, list[tuple[ParsedNativeTag, Path]]],
    module_base: str,
    cell: str,
) -> tuple[ParsedNativeTag, Path] | None:
    for parsed, path in arts.get(module_base, []):
        if parsed.catalog_key() == cell:
            return parsed, path
    return None


def _python_candidates(py_minor: str) -> list[str]:
    if not py_minor.isdigit() or len(py_minor) != 3:
        return []
    major, minor = py_minor[0], py_minor[1:]
    ver = f"python{major}.{minor}"
    root = os.environ.get("FLASHCLI_PYTHON_ROOT", "/opt/flashcli-python")
    override = os.environ.get(f"FLASHCLI_PY{py_minor}_BIN", "").strip()
    out: list[str] = []
    if override:
        out.append(override)
    out.extend(
        [
            ver,
            f"/usr/local/bin/{ver}",
            f"/usr/bin/{ver}",
            f"{root}/{major}.{minor}/bin/{ver}",
            f"/opt/python/{ver}/bin/{ver}",
        ]
    )
    return out


def resolve_python_for_minor(py_minor: str) -> Path | None:
    if host_python_minor() == py_minor:
        return Path(sys.executable)
    for cand in _python_candidates(py_minor):
        if "/" in cand:
            p = Path(cand)
            if not (p.is_file() and os.access(p, os.X_OK)):
                continue
        else:
            found = shutil.which(cand)
            if not found:
                continue
            p = Path(found)
        try:
            out = subprocess.run(
                [str(p), "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode != 0:
            continue
        m = re.match(r"\((\d+), (\d+)\)", out.stdout.strip())
        if not m:
            continue
        if int(m.group(1)) == int(py_minor[0]) and int(m.group(2)) == int(py_minor[1:]):
            return p.resolve()
    return None


def _classify_probe_failure(stderr: str, stdout: str) -> str:
    combined = f"{stderr}\n{stdout}"
    lower = combined.lower()
    if any(m in combined for m in _ABI_MISMATCH_MARKERS):
        return "abi_mismatch"
    if any(m.lower() in lower for m in _CUDA_LOAD_MARKERS):
        return "cuda_runtime"
    if any(m in combined for m in _ELF_BAD_MARKERS):
        return "invalid_elf"
    return "load_failed"


def probe_native_so_abi(path: Path, *, python_minor: str) -> str | None:
    """Return an error string if the .so cannot load under the tagged Python ABI."""
    py = resolve_python_for_minor(python_minor)
    if py is None:
        return (
            f"no Python {python_minor[0]}.{python_minor[1:]} interpreter found to verify "
            f"{path.name} (set FLASHCLI_PY{python_minor}_BIN)"
        )
    try:
        proc = subprocess.run(
            [str(py), "-c", _PROBE_SCRIPT, str(path.resolve())],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"timed out loading {path.name} with {py}"
    except OSError as exc:
        return f"cannot run {py}: {exc}"
    if proc.returncode == 0:
        return None
    kind = _classify_probe_failure(proc.stderr, proc.stdout)
    if kind == "abi_mismatch":
        return (
            f"{path.name}: Python ABI does not match filename tag -py{python_minor} "
            f"(probe with {py}): {(proc.stderr or proc.stdout).strip()[:240]}"
        )
    if kind == "cuda_runtime":
        return None
    detail = (proc.stderr or proc.stdout).strip().replace("\n", " ")[:240]
    return f"{path.name}: failed to load with {py} ({kind}): {detail}"


def validate_native_lib_matrix(bundle: BundleManifest) -> list[str]:
    """Check ``lib/`` matrix completeness and consistent tags per environment cell."""
    lib_dir = bundle_native_lib_dir(bundle.bundle_root, bundle_native_lib_rel(bundle))
    if not lib_dir.is_dir():
        return []

    errors: list[str] = []
    arts = list_native_artifacts(lib_dir)
    required = _required_module_bases(bundle, lib_dir)

    for path in sorted(lib_dir.glob("*.so")):
        if parse_native_tag_from_filename(path.name) is None:
            base = logical_native_module_name(path.name)
            if base not in NATIVE_MODULE_BASES and not path.name.startswith("libfmha"):
                errors.append(f"lib/{path.name}: unrecognized native artifact filename")

    if not bundle_uses_native_matrix(bundle.raw) and not _cells_present_in_lib(lib_dir):
        return errors

    expected_cells = _expected_matrix_cells(bundle, lib_dir)
    lib_cells = _cells_present_in_lib(lib_dir)

    if not expected_cells and not lib_cells:
        return errors

    if isinstance(bundle.raw.get("native_matrix"), list) and bundle.raw["native_matrix"]:
        for cell in sorted(expected_cells - lib_cells):
            errors.append(
                f"native_matrix lists {cell!r} but lib/ has no matching "
                f"flash_rt_kernels*-{cell}.so"
            )

    cells_to_check = expected_cells or lib_cells
    if not cells_to_check and any(lib_dir.glob("*.so")):
        errors.append(
            "lib/ contains .so files but no parseable matrix cells "
            "(expected tags like *-sm120-cu130-linux-x86_64-py310.so)"
        )
        return errors

    for cell in sorted(cells_to_check):
        refs: list[tuple[str, ParsedNativeTag]] = []
        for mod in required:
            found = _find_artifact(arts, mod, cell)
            if found is None:
                errors.append(f"missing lib/{mod}-*-{cell}.so")
                continue
            parsed, _path = found
            refs.append((mod, parsed))

        if len(refs) < 2:
            continue
        _mod0, ref = refs[0]
        for mod, tag in refs[1:]:
            if tag.python_minor != ref.python_minor:
                errors.append(
                    f"{cell}: inconsistent python_abi — {refs[0][0]} -py{ref.python_minor} "
                    f"vs {mod} -py{tag.python_minor}"
                )
            if (
                tag.sm,
                tag.cuda_tag,
                tag.os_name,
                tag.arch,
            ) != (ref.sm, ref.cuda_tag, ref.os_name, ref.arch):
                errors.append(
                    f"{cell}: inconsistent platform tags between {refs[0][0]} and {mod} "
                    f"(sm/cu/os/arch must match)"
                )
            if tag.flashrt_abi != ref.flashrt_abi:
                errors.append(
                    f"{cell}: inconsistent FlashRT ABI segment "
                    f"({refs[0][0]} {tag.flashrt_abi!r} vs {mod} {ref.flashrt_abi!r})"
                )

    return errors


def validate_native_lib_abi(bundle: BundleManifest) -> list[str]:
    """Probe-load each tagged ``lib/*.so`` with the Python version in its filename."""
    lib_dir = bundle_native_lib_dir(bundle.bundle_root, bundle_native_lib_rel(bundle))
    if not lib_dir.is_dir():
        return []

    errors: list[str] = []
    required = _required_module_bases(bundle, lib_dir)
    arts = list_native_artifacts(lib_dir)

    for mod in required:
        for parsed, path in arts.get(mod, []):
            err = probe_native_so_abi(path, python_minor=parsed.python_minor)
            if err:
                errors.append(err)

    return errors


def validate_native_lib(bundle: BundleManifest, *, probe_abi: bool = True) -> list[str]:
    errors = validate_native_lib_matrix(bundle)
    if probe_abi:
        errors.extend(validate_native_lib_abi(bundle))
    return errors
