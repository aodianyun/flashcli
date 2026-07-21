"""Bundle-isolated FlashRT-Nexus substrate loader.

Loads the three C shared libs (libflashrt_exec, libflashrt_cpp_pi05_c,
libcapsule_nexus_flashrt) plus the vendored ``nexus_python`` package from
this bundle's ``runtime/<env_key>/substrate/`` directory.

Design:
- Absolute-path ``ctypes.CDLL`` with ``RTLD_GLOBAL``; no LD_LIBRARY_PATH.
- Loads in dependency order: exec first (NEEDED by nexus), then producer,
  then nexus.
- Verifies the Nexus lib truly links the bundled FlashRT exec via ``ldd``.
- VERSION file is the single source of truth for the ABI fingerprint.
- ``flashcli bundle validate`` skips the ``substrate/`` subdir, so the C
  libs are invisible to the existing validator (which expects only pybind
  ``flash_rt_*`` modules at the cell top level).

Standalone: no flashcli_bundle import; only stdlib + ctypes.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _bundle_root() -> Path:
    """Active bundle root (set by flashcli) or this file's parent."""
    root = os.environ.get("FLASHCLI_BUNDLE_ROOT", "").strip()
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent


def _runtime_dir() -> Path:
    """runtime/<env_key>/ for the single env declared in flashcli-bundle.json."""
    manifest_path = _bundle_root() / "flashcli-bundle.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    runtime_map = manifest.get("runtime", {})
    if not runtime_map:
        raise RuntimeError("flashcli-bundle.json has no runtime map")
    if len(runtime_map) != 1:
        raise RuntimeError(
            f"_substrate_loader expects single-env bundle, got {list(runtime_map)}"
        )
    env_key = next(iter(runtime_map))
    return _bundle_root() / "runtime" / env_key


def substrate_dir() -> Path:
    """runtime/<env_key>/substrate/ — C libs + nexus_python live here."""
    return _runtime_dir() / "substrate"


def read_version() -> dict[str, Any]:
    v = substrate_dir() / "VERSION"
    if not v.is_file():
        raise RuntimeError(f"missing {v} (bundle built without Nexus support)")
    return json.loads(v.read_text())


def _glob_one(d: Path, pat: str) -> Path:
    matches = sorted(d.glob(pat))
    if not matches:
        raise RuntimeError(f"no file matching {pat!r} under {d}")
    if len(matches) > 1:
        raise RuntimeError(
            f"ambiguous {pat!r} under {d}: {[m.name for m in matches]}"
        )
    return matches[0]


def _verify_nexus_links_exec(nexus_so: Path) -> None:
    """ldd check: nexus.so MUST NEEDED the bundled exec."""
    try:
        out = subprocess.check_output(["ldd", str(nexus_so)], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"cannot ldd {nexus_so.name}: {exc}") from exc
    if "libflashrt_exec" not in out:
        raise RuntimeError(
            f"{nexus_so.name} does not link any libflashrt_exec — "
            "the bundle's Nexus + FlashRT pairing is broken."
        )


def _preload_pybind_module(name: str, path: Path) -> None:
    """Load a pybind .so from an absolute path and register it in sys.modules.

    This bypasses any sys.path ordering issues. The flashcli host process
    re-execs into the bundle venv, then ``activate_bundle`` prepends several
    paths to sys.path; relying on sys.path alone for ``_flashrt_exec`` and
    ``_flashrt_runtime`` discovery is fragile. Loading explicitly here, right
    after the C libraries, guarantees the modules are available when the
    Nexus producer plugin later imports ``flash_rt.runtime.exec`` /
    ``flash_rt.runtime.export``.
    """
    import importlib.util
    if not path.is_file():
        raise RuntimeError(f"missing pybind module {name} at {path}")
    if name in sys.modules:
        return  # already loaded (idempotent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create import spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # register before exec_module to handle self-imports
    spec.loader.exec_module(mod)


def load_substrate() -> dict[str, Any]:
    """Idempotent loader. Returns dict of paths + version + nexus_lib handle."""
    sub = substrate_dir()
    version = read_version()

    exec_so     = _glob_one(sub, "libflashrt_exec-*.so")
    producer_so = _glob_one(sub, "libflashrt_cpp_pi05_c-*.so")
    nexus_so    = _glob_one(sub, "libcapsule_nexus_flashrt-*.so")

    _verify_nexus_links_exec(nexus_so)

    # Loading order matters:
    # 1) exec — provides frt_* symbols; nexus NEEDEDs libflashrt_exec.so.1
    # 2) producer — model-specific native verbs (depends on flashrt_runtime,
    #    which is statically linked; independent of nexus)
    # 3) nexus — depends on exec at link time
    # RTLD_GLOBAL so cross-library symbol resolution works without LD_LIBRARY_PATH.
    ctypes.CDLL(str(exec_so),     mode=ctypes.RTLD_GLOBAL)
    ctypes.CDLL(str(producer_so), mode=ctypes.RTLD_GLOBAL)
    nexus_lib = ctypes.CDLL(str(nexus_so), mode=ctypes.RTLD_GLOBAL)

    # Pre-load the pybind dev modules _flashrt_exec and _flashrt_runtime into
    # sys.modules. flash_rt/runtime/exec.py and runtime/export.py import them
    # at module-load time (when the Nexus producer plugin calls
    # pipeline.export_model_runtime → exec_enable). Registering them here,
    # before any flashcli serve code reorders sys.path, makes the import
    # robust to sys.path manipulation by _add_flashrt_paths.
    for mod_name, mod_file in (
        ("_flashrt_exec",     "_flashrt_exec.cpython-310-x86_64-linux-gnu.so"),
        ("_flashrt_runtime",  "_flashrt_runtime.cpython-310-x86_64-linux-gnu.so"),
    ):
        _preload_pybind_module(mod_name, sub / mod_file)

    # Put the vendored nexus_python package on sys.path so consumers can
    # `from nexus_python.embedded import EmbeddedSession`. We add the
    # PARENT of nexus_python/ (i.e. substrate/) so Python resolves
    # `nexus_python` as a package.
    np = sub / "nexus_python"
    if not np.is_dir():
        raise RuntimeError(f"missing vendored nexus_python/ under {sub}")
    np_parent = str(np.parent)
    if np_parent not in sys.path:
        sys.path.insert(0, np_parent)

    return {
        "nexus_lib":    nexus_lib,
        "exec_so":      exec_so,
        "producer_so":  producer_so,
        "nexus_so":     nexus_so,
        "substrate_dir": sub,
        "version":      version,
    }


__all__ = [
    "load_substrate",
    "read_version",
    "substrate_dir",
    "_runtime_dir",
    "_bundle_root",
]
