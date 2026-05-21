"""Install flashcli vs FlashRT runtime Python dependencies via pip."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Literal

from flashcli.runtime.detect import torch_index_url
from flashcli.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    import_name_for_requirement,
    resolve_runtime_requirements,
)

Profile = Literal["default", "serve"]

# Installed by `pip install flashcli` (pyproject [project] dependencies).
FLASHCLI_PACKAGES = [
    "typer>=0.12",
    "pyyaml>=6.0",
    "packaging>=23.0",
    "huggingface_hub>=0.23",
]


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _imports_ok(spec: str) -> bool:
    mod = import_name_for_requirement(spec)
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _missing_runtime_imports(
    spec: RuntimeRequirementsSpec,
    profile: Profile = "default",
) -> list[str]:
    missing: list[str] = []
    for pkg in spec.all_packages_for_profile(profile):
        if not _imports_ok(pkg):
            missing.append(pkg)
    return missing


def flashcli_stack_satisfied() -> bool:
    return all(_imports_ok(p) for p in FLASHCLI_PACKAGES)


def runtime_python_stack_satisfied(
    spec: RuntimeRequirementsSpec,
    profile: Profile = "default",
) -> bool:
    return len(_missing_runtime_imports(spec, profile)) == 0


def python_stack_satisfied(
    profile: Profile = "default",
    *,
    runtime_dir: Path | None = None,
) -> bool:
    try:
        spec = resolve_runtime_requirements(runtime_dir)
    except RuntimeError:
        return False
    return runtime_python_stack_satisfied(spec, profile)


def _run_pip(args: list[str], *, quiet: bool) -> None:
    cmd = [sys.executable, "-m", "pip", "install", *args]
    if quiet:
        cmd.append("-q")
    subprocess.run(cmd, check=True)


def ensure_flashcli_stack(*, quiet: bool = False, force: bool = False) -> None:
    """pip install flashcli CLI dependencies (doctor, pull, registry)."""
    if not force and flashcli_stack_satisfied():
        return
    to_install = [p for p in FLASHCLI_PACKAGES if force or not _imports_ok(p)]
    if not to_install:
        return
    if not quiet:
        print(f"Installing flashcli dependencies: {', '.join(to_install)}")
    _run_pip(to_install, quiet=quiet)


def ensure_runtime_python_stack(
    *,
    runtime_dir: Path | None = None,
    torch_index: str = "cu124",
    profile: Profile = "default",
    quiet: bool = False,
    force: bool = False,
) -> None:
    """pip install torch (CUDA index) + requirements from runtime bundle / FlashRT pyproject."""
    spec = resolve_runtime_requirements(runtime_dir)

    if not force and runtime_python_stack_satisfied(spec, profile):
        return

    if not quiet:
        print(f"Runtime Python requirements from: {spec.source}")

    if spec.torch_package.strip():
        index_url = torch_index_url(torch_index)
        if not _imports_ok(spec.torch_package) or force:
            if not quiet:
                print(f"Installing {spec.torch_package} from {index_url} ...")
            _run_pip(
                [spec.torch_package, "--index-url", index_url],
                quiet=quiet,
            )

    to_install = [
        p
        for p in spec.packages_for_profile(profile)
        if force or not _imports_ok(p)
    ]

    if to_install:
        if not quiet:
            print(f"Installing FlashRT runtime dependencies: {', '.join(to_install)}")
        _run_pip(to_install, quiet=quiet)

    missing = _missing_runtime_imports(spec, profile)
    if missing:
        if not quiet:
            print(f"Retrying missing imports: {', '.join(missing)}")
        _run_pip(missing, quiet=quiet)
        missing = _missing_runtime_imports(spec, profile)
    if missing:
        names = ", ".join(import_name_for_requirement(p) for p in missing)
        raise RuntimeError(
            f"FlashRT runtime Python dependencies still missing after pip install: {names}\n"
            f"Spec source: {spec.source}\n"
            "Try: flashcli doctor --install --force\n"
            "Or rebuild runtime package with current FlashRT pyproject.toml"
        )


def ensure_python_stack(
    *,
    runtime_dir: Path | None = None,
    torch_index: str = "cu124",
    profile: Profile = "default",
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Backward-compatible alias for ensure_runtime_python_stack."""
    ensure_runtime_python_stack(
        runtime_dir=runtime_dir,
        torch_index=torch_index,
        profile=profile,
        quiet=quiet,
        force=force,
    )
