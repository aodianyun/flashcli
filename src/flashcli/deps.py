"""Install flashcli vs bundle (inference runtime) Python dependencies via pip."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from flashcli.runtime.mirror import (
    pip_index_url,
    pip_install_extra_args,
    pip_trusted_host,
    resolve_torch_index_url,
)
from flashcli.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    import_name_for_requirement,
    resolve_runtime_requirements,
)

# Installed with flashcli (pyproject [project] dependencies).
FLASHCLI_CORE_PACKAGES = [
    "typer>=0.12",
    "pyyaml>=6.0",
    "packaging>=23.0",
    "huggingface_hub>=0.26",
]

# flashcli unified HTTP API (src/flashcli/serve — not bundle inference code).
FLASHCLI_SERVE_PACKAGES = [
    "fastapi>=0.100",
    "uvicorn[standard]>=0.24",
]

# Backward-compatible alias.
FLASHCLI_PACKAGES = FLASHCLI_CORE_PACKAGES


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _imports_ok(spec: str) -> bool:
    mod = import_name_for_requirement(spec)
    if mod == "huggingface_hub":
        return _module_available(mod)
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _missing_imports(packages: list[str]) -> list[str]:
    return [p for p in packages if not _imports_ok(p)]


def _missing_runtime_imports(spec: RuntimeRequirementsSpec) -> list[str]:
    missing: list[str] = []
    for pkg in spec.all_packages():
        if not _imports_ok(pkg):
            missing.append(pkg)
    return missing


def flashcli_core_stack_satisfied() -> bool:
    return not _missing_imports(FLASHCLI_CORE_PACKAGES)


def flashcli_serve_stack_satisfied() -> bool:
    return not _missing_imports(FLASHCLI_SERVE_PACKAGES)


def flashcli_stack_satisfied(*, include_serve: bool = False) -> bool:
    if not flashcli_core_stack_satisfied():
        return False
    if include_serve and not flashcli_serve_stack_satisfied():
        return False
    return True


def bundle_python_stack_satisfied(*, bundle_root: Path) -> bool:
    try:
        spec = resolve_runtime_requirements(bundle_root=bundle_root)
    except RuntimeError:
        return False
    return len(_missing_runtime_imports(spec)) == 0


def python_stack_satisfied(
    *,
    runtime_dir: Path | None = None,
    bundle_root: Path | None = None,
) -> bool:
    """Backward-compatible alias for bundle inference stack check."""
    root = bundle_root or runtime_dir
    if root is None:
        return False
    return bundle_python_stack_satisfied(bundle_root=root)


def _run_pip(args: list[str], *, quiet: bool, use_pypi_mirror: bool = True) -> None:
    cmd = [sys.executable, "-m", "pip", "install"]
    if use_pypi_mirror:
        cmd.extend(pip_install_extra_args())
    cmd.extend(args)
    if quiet:
        cmd.append("-q")
    subprocess.run(cmd, check=True)


def ensure_flashcli_core_stack(*, quiet: bool = False, force: bool = False) -> None:
    """pip install flashcli CLI dependencies (typer, huggingface_hub, …)."""
    to_install = [
        p for p in FLASHCLI_CORE_PACKAGES if force or not _imports_ok(p)
    ]
    if not to_install:
        return
    if not quiet:
        print(f"Installing flashcli dependencies: {', '.join(to_install)}")
    _run_pip(to_install, quiet=quiet)


def ensure_flashcli_serve_stack(*, quiet: bool = False, force: bool = False) -> None:
    """pip install flashcli HTTP serve layer (fastapi, uvicorn)."""
    to_install = [
        p for p in FLASHCLI_SERVE_PACKAGES if force or not _imports_ok(p)
    ]
    if not to_install:
        return
    if not quiet:
        print(f"Installing flashcli serve dependencies: {', '.join(to_install)}")
    _run_pip(to_install, quiet=quiet)


def ensure_flashcli_stack(
    *,
    quiet: bool = False,
    force: bool = False,
    include_serve: bool = False,
) -> None:
    """Install flashcli core (+ optional serve HTTP) dependencies."""
    ensure_flashcli_core_stack(quiet=quiet, force=force)
    if include_serve:
        ensure_flashcli_serve_stack(quiet=quiet, force=force)


def repair_flashcli_serve_stack(*, quiet: bool = False) -> None:
    ensure_flashcli_serve_stack(quiet=quiet, force=True)


def ensure_runtime_python_stack(
    *,
    runtime_dir: Path | None = None,
    bundle_root: Path | None = None,
    torch_index: str = "cu124",
    quiet: bool = False,
    force: bool = False,
) -> None:
    """pip install bundle inference stack (torch + flashcli-bundle.json / FlashRT)."""
    root = bundle_root or runtime_dir
    spec = resolve_runtime_requirements(runtime_dir, bundle_root=root)

    if not force and not _missing_runtime_imports(spec):
        return

    if not quiet:
        print(f"Installing bundle Python dependencies from: {spec.source}")

    if spec.torch_package.strip():
        index_url = resolve_torch_index_url(torch_index)
        if not _imports_ok(spec.torch_package) or force:
            if not quiet:
                print(f"Installing {spec.torch_package} from {index_url} ...")
            torch_args = [spec.torch_package, "--index-url", index_url]
            pypi = pip_index_url()
            if pypi:
                torch_args.extend(["--extra-index-url", pypi])
                host = pip_trusted_host()
                if host:
                    torch_args.extend(["--trusted-host", host])
            _run_pip(torch_args, quiet=quiet, use_pypi_mirror=False)

    to_install = [
        p for p in spec.pip_packages if force or not _imports_ok(p)
    ]

    if to_install:
        if not quiet:
            print(f"Installing bundle runtime dependencies: {', '.join(to_install)}")
        _run_pip(to_install, quiet=quiet)

    missing = _missing_runtime_imports(spec)
    if missing:
        if not quiet:
            print(f"Retrying missing bundle imports: {', '.join(missing)}")
        _run_pip(missing, quiet=quiet)
        missing = _missing_runtime_imports(spec)
    if missing:
        names = ", ".join(import_name_for_requirement(p) for p in missing)
        raise RuntimeError(
            f"Bundle Python dependencies still missing after pip install: {names}\n"
            f"Spec source: {spec.source}\n"
            "Try: flashcli bundle install <bundle>"
        )


def repair_bundle_python_stack(
    *,
    bundle_root: Path,
    torch_index: str = "cu124",
    quiet: bool = False,
) -> None:
    """Re-run bundle pip install when imports fail after activate."""
    ensure_runtime_python_stack(
        bundle_root=bundle_root,
        torch_index=torch_index,
        quiet=quiet,
        force=True,
    )


def ensure_python_stack(
    *,
    runtime_dir: Path | None = None,
    bundle_root: Path | None = None,
    torch_index: str = "cu124",
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Backward-compatible alias for ensure_runtime_python_stack."""
    ensure_runtime_python_stack(
        runtime_dir=runtime_dir,
        bundle_root=bundle_root or runtime_dir,
        torch_index=torch_index,
        quiet=quiet,
        force=force,
    )
