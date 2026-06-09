"""Validate ``runtime/<env-key>/`` native completeness and Python ABI vs filename tags."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from flashcli.bundle.manifest import BundleManifest, bundle_runtime_map
from flashcli.bundle.native_naming import (
    NATIVE_MODULE_BASES,
    ParsedNativeTag,
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
try:
    spec.loader.exec_module(mod)
except ImportError as exc:
    msg = str(exc)
    if "Python version mismatch" in msg or "interpreter version is incompatible" in msg:
        print(msg, file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(0) from exc
"""


def _required_module_bases(_bundle: BundleManifest, native_dir: Path) -> tuple[str, ...]:
    bases: list[str] = ["flash_rt_kernels", "flash_rt_fa2"]
    if any(native_dir.glob("flash_rt_fp4*.so")):
        bases.append("flash_rt_fp4")
    return tuple(bases)


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
    if proc.returncode == 2:
        return (
            f"{path.name}: Python ABI does not match filename tag -py{python_minor} "
            f"(probe with {py}): {(proc.stderr or proc.stdout).strip()[:240]}"
        )
    kind = _classify_probe_failure(proc.stderr, proc.stdout)
    if kind == "abi_mismatch":
        return (
            f"{path.name}: Python ABI does not match filename tag -py{python_minor} "
            f"(probe with {py}): {(proc.stderr or proc.stdout).strip()[:240]}"
        )
    if kind in ("cuda_runtime", "load_failed"):
        return None
    detail = (proc.stderr or proc.stdout).strip().replace("\n", " ")[:240]
    return f"{path.name}: failed to load with {py} ({kind}): {detail}"


def _validate_runtime_cell(
    bundle: BundleManifest,
    env_key: str,
    native_dir: Path,
) -> list[str]:
    rel = native_dir.relative_to(bundle.bundle_root)
    errors: list[str] = []
    if not native_dir.is_dir():
        return [f"missing {rel}/ for runtime {env_key!r}"]

    arts = list_native_artifacts(native_dir)
    required = _required_module_bases(bundle, native_dir)

    for path in sorted(native_dir.glob("*.so")):
        parsed = parse_native_tag_from_filename(path.name)
        if parsed is None:
            base = logical_native_module_name(path.name)
            if base not in NATIVE_MODULE_BASES and not path.name.startswith("libfmha"):
                errors.append(f"{rel}/{path.name}: unrecognized native artifact filename")
            continue
        if parsed.catalog_key() != env_key:
            errors.append(
                f"{rel}/{path.name}: filename tag {parsed.catalog_key()!r} "
                f"does not match runtime cell {env_key!r}"
            )

    refs: list[tuple[str, ParsedNativeTag]] = []
    for mod in required:
        found = _find_artifact(arts, mod, env_key)
        if found is None:
            errors.append(f"missing {rel}/{mod}-*-{env_key}.so")
            continue
        parsed, _path = found
        refs.append((mod, parsed))

    if len(refs) >= 2:
        _mod0, ref = refs[0]
        for mod, tag in refs[1:]:
            if tag.python_minor != ref.python_minor:
                errors.append(
                    f"{env_key}: inconsistent python_abi — {refs[0][0]} -py{ref.python_minor} "
                    f"vs {mod} -py{tag.python_minor}"
                )
            if (
                tag.sm,
                tag.cuda_tag,
                tag.os_name,
                tag.arch,
            ) != (ref.sm, ref.cuda_tag, ref.os_name, ref.arch):
                errors.append(
                    f"{env_key}: inconsistent platform tags between {refs[0][0]} and {mod} "
                    f"(sm/cu/os/arch must match)"
                )
            if tag.flashrt_abi != ref.flashrt_abi:
                errors.append(
                    f"{env_key}: inconsistent FlashRT ABI segment "
                    f"({refs[0][0]} {tag.flashrt_abi!r} vs {mod} {ref.flashrt_abi!r})"
                )

    return errors


def validate_native_runtime_matrix(bundle: BundleManifest) -> list[str]:
    """Check each manifest ``runtime/<env-key>/`` directory for required ``.so`` files."""
    try:
        runtime_map = bundle_runtime_map(bundle)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    for env_key, rel_path in runtime_map.items():
        native_dir = (bundle.bundle_root / rel_path.strip().lstrip("/")).resolve()
        errors.extend(_validate_runtime_cell(bundle, env_key, native_dir))
    return errors


def validate_native_runtime_abi(bundle: BundleManifest) -> list[str]:
    """Probe-load each tagged ``runtime/<env-key>/*.so`` with its filename Python ABI."""
    errors: list[str] = []
    try:
        runtime_map = bundle_runtime_map(bundle)
    except ValueError:
        return errors

    for _env_key, rel_path in runtime_map.items():
        native_dir = (bundle.bundle_root / rel_path.strip().lstrip("/")).resolve()
        if not native_dir.is_dir():
            continue
        required = _required_module_bases(bundle, native_dir)
        arts = list_native_artifacts(native_dir)
        for mod in required:
            for parsed, path in arts.get(mod, []):
                err = probe_native_so_abi(path, python_minor=parsed.python_minor)
                if err:
                    errors.append(err)
    return errors


def validate_native_runtime(
    bundle: BundleManifest,
    *,
    probe_abi: bool = True,
    env_key: str | None = None,
) -> list[str]:
    if env_key is None:
        errors = validate_native_runtime_matrix(bundle)
        cells: list[tuple[str, Path]] = []
        try:
            for key, rel in bundle_runtime_map(bundle).items():
                cells.append(
                    (key, (bundle.bundle_root / rel.strip().lstrip("/")).resolve())
                )
        except ValueError:
            cells = []
    else:
        try:
            rel = bundle_runtime_map(bundle)[env_key]
        except (ValueError, KeyError):
            return validate_native_runtime_matrix(bundle)
        native_dir = (bundle.bundle_root / rel.strip().lstrip("/")).resolve()
        errors = _validate_runtime_cell(bundle, env_key, native_dir)
        cells = [(env_key, native_dir)]

    if probe_abi:
        for _key, native_dir in cells:
            if not native_dir.is_dir():
                continue
            required = _required_module_bases(bundle, native_dir)
            arts = list_native_artifacts(native_dir)
            for mod in required:
                for parsed, path in arts.get(mod, []):
                    err = probe_native_so_abi(path, python_minor=parsed.python_minor)
                    if err:
                        errors.append(err)
    return errors


# Backward-compatible aliases for tests / internal imports
validate_native_lib = validate_native_runtime
validate_native_lib_matrix = validate_native_runtime_matrix
validate_native_lib_abi = validate_native_runtime_abi
