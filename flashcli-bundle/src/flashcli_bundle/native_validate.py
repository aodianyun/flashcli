"""Validate ``runtime/<env-key>/`` native completeness and Python ABI vs filename tags."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from flashcli_bundle.manifest_ext import BundleManifest, bundle_runtime_map
from flashcli_bundle.native_naming import (
    ParsedNativeTag,
    discover_native_module_bases,
    list_native_artifacts,
    parse_native_tag_from_filename,
)
from flashcli_bundle.runtime_env import host_python_minor

PythonForMinorFn = Callable[[str], Path | None]

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


def _required_module_bases(
    _bundle: BundleManifest,
    native_dir: Path,
    *,
    env_key: str,
) -> tuple[str, ...]:
    """Modules declared by ``*.so`` files under ``runtime/<env-key>/``."""
    return discover_native_module_bases(native_dir, env_key=env_key)


def _find_artifact(
    arts: dict[str, list[tuple[ParsedNativeTag, Path]]],
    module_base: str,
    cell: str,
) -> tuple[ParsedNativeTag, Path] | None:
    for parsed, path in arts.get(module_base, []):
        if parsed.catalog_key() == cell:
            return parsed, path
    return None


def _default_python_for_minor(py_minor: str) -> Path | None:
    """Infer-safe resolver: current interpreter or ``FLASHCLI_PY{minor}_BIN``."""
    if host_python_minor() == py_minor:
        return Path(sys.executable)
    override = os.environ.get(f"FLASHCLI_PY{py_minor}_BIN", "").strip()
    if override:
        p = Path(override).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
    return None


def probe_native_so_abi(
    path: Path,
    *,
    python_minor: str,
    python_for_minor: PythonForMinorFn | None = None,
) -> str | None:
    """Return an error string if the .so cannot load under the tagged Python ABI."""
    resolve = python_for_minor or _default_python_for_minor
    py = resolve(python_minor)
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


def _validate_runtime_cell(
    bundle: BundleManifest,
    env_key: str,
    native_dir: Path,
) -> list[str]:
    rel = native_dir.relative_to(bundle.bundle_root)
    errors: list[str] = []
    if not native_dir.is_dir():
        return [f"missing {rel}/ for runtime {env_key!r}"]

    arts = list_native_artifacts(native_dir, env_key=env_key)
    matched_modules: set[str] = set()

    for path in sorted(native_dir.glob("*.so")):
        parsed = parse_native_tag_from_filename(path.name, env_key=env_key)
        if parsed is None:
            inferred = parse_native_tag_from_filename(path.name)
            if inferred is not None and inferred.catalog_key() != env_key:
                errors.append(
                    f"{rel}/{path.name}: filename tag {inferred.catalog_key()!r} "
                    f"does not match runtime cell {env_key!r}"
                )
            else:
                errors.append(
                    f"{rel}/{path.name}: unrecognized native artifact filename "
                    f"(expected *-*-{env_key}.so)"
                )
            continue
        if parsed.catalog_key() != env_key:
            errors.append(
                f"{rel}/{path.name}: filename tag {parsed.catalog_key()!r} "
                f"does not match runtime cell {env_key!r}"
            )
            continue
        matched_modules.add(parsed.module_base)

    if not matched_modules:
        errors.append(
            f"{rel}/ has no recognized native .so artifacts "
            f"(expected tagged files such as *-*-{env_key}.so)"
        )
        return errors

    required = tuple(sorted(matched_modules))
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
            if tag.env_key != ref.env_key:
                errors.append(
                    f"{env_key}: inconsistent env key between {refs[0][0]} and {mod} "
                    f"({ref.env_key!r} vs {tag.env_key!r})"
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


def validate_native_runtime_abi(
    bundle: BundleManifest,
    *,
    python_for_minor: PythonForMinorFn | None = None,
) -> list[str]:
    """Probe-load each tagged ``runtime/<env-key>/*.so`` with its filename Python ABI."""
    errors: list[str] = []
    try:
        runtime_map = bundle_runtime_map(bundle)
    except ValueError:
        return errors

    for env_key, rel_path in runtime_map.items():
        native_dir = (bundle.bundle_root / rel_path.strip().lstrip("/")).resolve()
        if not native_dir.is_dir():
            continue
        required = _required_module_bases(bundle, native_dir, env_key=env_key)
        arts = list_native_artifacts(native_dir, env_key=env_key)
        for mod in required:
            for parsed, path in arts.get(mod, []):
                err = probe_native_so_abi(
                    path,
                    python_minor=parsed.python_minor,
                    python_for_minor=python_for_minor,
                )
                if err:
                    errors.append(err)
    return errors


def validate_native_runtime(
    bundle: BundleManifest,
    *,
    probe_abi: bool = True,
    env_key: str | None = None,
    python_for_minor: PythonForMinorFn | None = None,
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
        for key, native_dir in cells:
            if not native_dir.is_dir():
                continue
            required = _required_module_bases(bundle, native_dir, env_key=key)
            arts = list_native_artifacts(native_dir, env_key=key)
            for mod in required:
                for parsed, path in arts.get(mod, []):
                    err = probe_native_so_abi(
                        path,
                        python_minor=parsed.python_minor,
                        python_for_minor=python_for_minor,
                    )
                    if err:
                        errors.append(err)
    return errors
