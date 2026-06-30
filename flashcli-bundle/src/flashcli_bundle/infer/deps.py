"""Install bundle inference dependencies into the bundle venv."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from email import message_from_string
from pathlib import Path

from flashcli_bundle import paths as config
from flashcli_bundle.infer.runtime.mirror import (
    pip_index_url,
    pip_install_extra_args,
    pip_trusted_host,
    resolve_torch_index_url,
)
from flashcli_bundle.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    import_name_for_requirement,
    pip_nodeps_names,
    requirement_import_satisfied,
    requirement_needs_pip_install,
    requirement_package_name,
    resolve_runtime_requirements,
    uses_torch_cuda_wheel_index,
)

_INFER_EXTRA = "infer"


def _pip_python(python: Path | None) -> str:
    return str(python) if python is not None else sys.executable


def _module_available(name: str, *, python: Path | None = None) -> bool:
    py = _pip_python(python)
    proc = subprocess.run(
        [py, "-c", f"import importlib.util; raise SystemExit(0 if importlib.util.find_spec({name!r}) else 1)"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _imports_ok(
    spec: str,
    *,
    python: Path | None = None,
    bundle_root: Path | None = None,
) -> bool:
    return requirement_import_satisfied(
        spec, python=_pip_python(python), bundle_root=bundle_root
    )


def _missing_runtime_imports(
    spec: RuntimeRequirementsSpec,
    *,
    python: Path | None = None,
    bundle_root: Path | None = None,
) -> list[str]:
    missing = [
        p
        for p in spec.all_packages()
        if not _imports_ok(p, python=python, bundle_root=bundle_root)
    ]
    for pkg in spec.pip_packages:
        if not uses_torch_cuda_wheel_index(pkg):
            continue
        if pkg in missing:
            continue
        if _imports_ok(pkg, python=python, bundle_root=bundle_root) and not _torch_cuda_wheel_stack_ok(
            python=python
        ):
            missing.append(pkg)
    if spec.torch_package.strip() and not _torch_cuda_wheel_stack_ok(python=python):
        for wheel in _TORCH_CUDA_COMPANION_WHEELS:
            if wheel not in missing:
                missing.append(wheel)
    return missing


def bundle_python_stack_satisfied(
    *, bundle_root: Path, python: Path | None = None
) -> bool:
    try:
        spec = resolve_runtime_requirements(bundle_root=bundle_root)
    except RuntimeError:
        return False
    return len(_missing_runtime_imports(spec, python=python, bundle_root=bundle_root)) == 0


def _run_pip(
    args: list[str],
    *,
    python: Path | None = None,
    quiet: bool,
    use_pypi_mirror: bool = True,
    no_deps: bool = False,
) -> None:
    cmd = [_pip_python(python), "-m", "pip", "install"]
    if no_deps:
        cmd.append("--no-deps")
    if use_pypi_mirror:
        cmd.extend(pip_install_extra_args())
    cmd.extend(args)
    if quiet:
        cmd.append("-q")
    subprocess.run(cmd, check=True)


def _torch_index_pip_args(
    packages: list[str],
    torch_index: str,
) -> list[str]:
    index_url = resolve_torch_index_url(torch_index)
    args = list(packages) + ["--index-url", index_url]
    pypi = pip_index_url()
    if pypi:
        args.extend(["--extra-index-url", pypi])
        host = pip_trusted_host()
        if host:
            args.extend(["--trusted-host", host])
    return args


def _pip_install_torch_index_packages(
    packages: list[str],
    *,
    torch_index: str,
    python: Path | None = None,
    quiet: bool,
    force_reinstall: bool = False,
) -> None:
    if not packages:
        return
    if not quiet:
        index_url = resolve_torch_index_url(torch_index)
        print(
            f"Installing PyTorch CUDA wheels from {index_url}: "
            f"{', '.join(packages)}"
        )
    args = _torch_index_pip_args(packages, torch_index)
    if force_reinstall:
        args = ["--force-reinstall", *args]
    _run_pip(args, quiet=quiet, use_pypi_mirror=False, python=python)


def _ensure_torch_cuda_companion_wheels(
    *,
    torch_index: str,
    python: Path | None = None,
    quiet: bool,
    force_reinstall: bool = False,
) -> None:
    """Install torchaudio/torchvision from the same CUDA index as torch."""
    if not force_reinstall and _torch_cuda_wheel_stack_ok(python=python):
        return
    _pip_install_torch_index_packages(
        list(_TORCH_CUDA_COMPANION_WHEELS),
        torch_index=torch_index,
        python=python,
        quiet=quiet,
        force_reinstall=force_reinstall,
    )


def _wheel_requires_excluding_torch(
    package_spec: str,
    *,
    python: Path | None = None,
    quiet: bool,
) -> list[str]:
    """Read PyPI wheel METADATA and drop torch CUDA wheel requirements."""
    from packaging.requirements import Requirement

    py = _pip_python(python)
    with tempfile.TemporaryDirectory(prefix="flashcli-pip-meta-") as tmp:
        cmd = [py, "-m", "pip", "download", package_spec, "-d", tmp, "--no-deps"]
        cmd.extend(pip_install_extra_args())
        if quiet:
            cmd.append("-q")
        subprocess.run(cmd, check=True)
        wheels = sorted(Path(tmp).glob("*.whl"))
        if not wheels:
            return []
        with zipfile.ZipFile(wheels[0]) as zf:
            meta_path = next(
                (name for name in zf.namelist() if name.endswith(".dist-info/METADATA")),
                None,
            )
            if meta_path is None:
                return []
            meta = message_from_string(zf.read(meta_path).decode())
    skip = _TORCH_CUDA_COMPANION_WHEELS + ("torch", "pytorch")
    out: list[str] = []
    seen: set[str] = set()
    for raw in meta.get_all("Requires-Dist") or []:
        req = Requirement(str(raw))
        name = req.name.lower()
        if name in skip:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(str(req))
    return out


def _install_pypi_nodeps_packages(
    packages: list[str],
    *,
    python: Path | None = None,
    quiet: bool,
    bundle_root: Path | None,
    force: bool,
) -> None:
    """Install packages without pulling transitive torch CUDA wheels from PyPI."""
    for package_spec in packages:
        prereqs = _wheel_requires_excluding_torch(
            package_spec, python=python, quiet=quiet
        )
        needed_prereqs = [
            req
            for req in prereqs
            if requirement_needs_pip_install(
                req,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=force,
            )
        ]
        if needed_prereqs:
            if not quiet:
                print(
                    f"Installing prerequisites for {package_spec}: "
                    f"{', '.join(needed_prereqs)}"
                )
            _run_pip(needed_prereqs, quiet=quiet, python=python)
        if not requirement_needs_pip_install(
            package_spec,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        ):
            continue
        if not quiet:
            print(f"Installing {package_spec} (--no-deps)")
        _run_pip([package_spec], quiet=quiet, python=python, no_deps=True)


def _finalize_torch_cuda_companion_wheels(
    *,
    torch_index: str,
    python: Path | None = None,
    quiet: bool,
) -> None:
    if not _torch_cuda_wheel_stack_ok(python=python):
        if not quiet:
            print("Repairing torchaudio/torchvision CUDA mismatch from PyPI deps ...")
        _ensure_torch_cuda_companion_wheels(
            torch_index=torch_index,
            python=python,
            quiet=quiet,
            force_reinstall=True,
        )


_TORCH_CUDA_COMPANION_WHEELS = ("torchaudio", "torchvision")

_TORCH_CUDA_STACK_PROBE = """
import torch
try:
    import torchaudio
except ImportError:
    raise SystemExit(1)
except RuntimeError as exc:
    msg = str(exc)
    if "different CUDA versions" in msg or "compiled with different CUDA versions" in msg:
        raise SystemExit(1) from exc
    raise
raise SystemExit(0)
"""


def _torch_cuda_wheel_stack_ok(*, python: Path | None = None) -> bool:
    """True when torchaudio is installed and matches torch's CUDA userland."""
    py = _pip_python(python)
    proc = subprocess.run(
        [py, "-c", _TORCH_CUDA_STACK_PROBE],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _needs_torch_cuda_wheel_reinstall(
    spec: str,
    *,
    python: Path | None = None,
    bundle_root: Path | None = None,
    force: bool = False,
) -> bool:
    if not uses_torch_cuda_wheel_index(spec):
        return False
    if force:
        return True
    if not _imports_ok(spec, python=python, bundle_root=bundle_root):
        return True
    return not _torch_cuda_wheel_stack_ok(python=python)


def _load_persisted_install_env() -> None:
    path = config.FLASHCLI_HOME / "install.env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val:
            os.environ.setdefault(key, val)


def _pip_spec_from_direct_url(
    dist_name: str,
    *,
    subdirectory: str | None = None,
    extras: tuple[str, ...] = (),
) -> str | None:
    try:
        from importlib.metadata import distribution

        data = json.loads(distribution(dist_name).read_text("direct_url.json"))
    except (ImportError, OSError, KeyError, TypeError, json.JSONDecodeError):
        return None

    pkg = dist_name.replace("_", "-")
    extra_suffix = f"[{','.join(extras)}]" if extras else ""
    vcs = data.get("vcs_info") if isinstance(data.get("vcs_info"), dict) else {}
    if isinstance(vcs, dict) and vcs.get("vcs") == "git":
        url = str(data.get("url", "")).strip()
        if not url:
            return None
        ref = str(
            vcs.get("requested_revision") or vcs.get("commit_id") or "main"
        ).strip()
        sub = subdirectory or str(data.get("subdirectory") or "").strip()
        spec = f"git+{url}@{ref}"
        if sub:
            spec += f"#subdirectory={sub}"
        return f"{pkg}{extra_suffix} @ {spec}"

    dir_info = data.get("dir_info") if isinstance(data.get("dir_info"), dict) else {}
    if dir_info.get("editable"):
        url = str(data.get("url", "")).strip()
        if not url:
            return None
        root = Path(url).expanduser().resolve()
        sub = subdirectory or str(data.get("subdirectory") or "").strip()
        if sub:
            candidate = root / sub
            if (candidate / "pyproject.toml").is_file():
                root = candidate
        if (root / "pyproject.toml").is_file():
            return str(root)
    return None


def flashcli_bundle_pip_spec(*, extras: tuple[str, ...] = (_INFER_EXTRA,)) -> str:
    import flashcli_bundle

    _load_persisted_install_env()

    extra_suffix = f"[{','.join(extras)}]" if extras else ""
    pkg_dir = Path(flashcli_bundle.__file__).resolve().parent
    src_root = pkg_dir.parent
    repo_root = src_root.parent
    if src_root.name == "src" and (repo_root / "pyproject.toml").is_file():
        text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        if 'name = "flashcli-bundle"' in text:
            if extras:
                return f"{repo_root}[{','.join(extras)}]"
            return str(repo_root)

    spec = _pip_spec_from_direct_url("flashcli-bundle", extras=extras)
    if spec:
        return spec

    spec = _pip_spec_from_direct_url("flashcli", subdirectory="flashcli-bundle", extras=extras)
    if spec:
        if spec.startswith("flashcli @ "):
            return f"flashcli-bundle{extra_suffix} @ " + spec.split(" @ ", 1)[1]
        return spec

    repo = os.environ.get("FLASHCLI_INSTALL_REPO", "").strip()
    ref = os.environ.get("FLASHCLI_INSTALL_REF", "main").strip() or "main"
    if repo:
        return f"flashcli-bundle{extra_suffix} @ git+{repo}@{ref}#subdirectory=flashcli-bundle"

    raise RuntimeError(
        "Cannot resolve flashcli-bundle install source for bundle venv. "
        "Reinstall flashcli from git (install.sh) or set "
        "FLASHCLI_INSTALL_REPO / FLASHCLI_INSTALL_REF (or ~/.flashcli/install.env)."
    )


def ensure_flashcli_bundle_in_venv(
    *,
    python: Path,
    quiet: bool = False,
    force: bool = False,
    extras: tuple[str, ...] = (_INFER_EXTRA,),
) -> None:
    if not force and _module_available("flashcli_bundle.infer", python=python):
        return
    spec = flashcli_bundle_pip_spec(extras=extras)
    if not quiet:
        label = f"[{','.join(extras)}]" if extras else ""
        print(f"Installing flashcli-bundle{label} into bundle venv ({spec}) ...")
    if " @ " not in spec:
        _run_pip(["-e", spec], quiet=quiet, python=python)
    else:
        _run_pip([spec], quiet=quiet, python=python)


def ensure_bundle_infer_deps(
    *,
    python: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    if python is None:
        return
    ensure_flashcli_bundle_in_venv(python=python, quiet=quiet, force=force, extras=(_INFER_EXTRA,))


def ensure_runtime_python_stack(
    *,
    bundle_root: Path | None = None,
    torch_index: str = "cu124",
    python: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    if bundle_root is None:
        raise ValueError("bundle_root is required")
    if python is not None:
        ensure_flashcli_bundle_in_venv(python=python, quiet=quiet, force=force)
    spec = resolve_runtime_requirements(bundle_root=bundle_root)

    if not force and not _missing_runtime_imports(
        spec, python=python, bundle_root=bundle_root
    ):
        return

    if not quiet:
        print(f"Installing bundle Python dependencies from: {spec.source}")

    nodeps_names = pip_nodeps_names(spec)

    if spec.torch_package.strip():
        index_url = resolve_torch_index_url(torch_index)
        if requirement_needs_pip_install(
            spec.torch_package,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        ):
            if not quiet:
                print(f"Installing {spec.torch_package} from {index_url} ...")
            _run_pip(
                _torch_index_pip_args([spec.torch_package], torch_index),
                quiet=quiet,
                use_pypi_mirror=False,
                python=python,
            )

    pending = [
        p
        for p in spec.pip_packages
        if _needs_torch_cuda_wheel_reinstall(
            p,
            python=python,
            bundle_root=bundle_root,
            force=force,
        )
        or (
            not uses_torch_cuda_wheel_index(p)
            and requirement_package_name(p) not in nodeps_names
            and requirement_needs_pip_install(
                p,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=force,
            )
        )
    ]
    torch_wheel_pkgs = [p for p in pending if uses_torch_cuda_wheel_index(p)]
    pypi_pkgs = [
        p
        for p in pending
        if not uses_torch_cuda_wheel_index(p) and requirement_package_name(p) not in nodeps_names
    ]
    nodeps_pkgs = [
        p
        for p in spec.pip_packages
        if requirement_package_name(p) in nodeps_names
        and requirement_needs_pip_install(
            p,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        )
    ]

    if torch_wheel_pkgs:
        _pip_install_torch_index_packages(
            torch_wheel_pkgs,
            torch_index=torch_index,
            python=python,
            quiet=quiet,
        )
    if spec.torch_package.strip():
        _ensure_torch_cuda_companion_wheels(
            torch_index=torch_index,
            python=python,
            quiet=quiet,
        )
    if pypi_pkgs:
        if not quiet:
            print(f"Installing bundle runtime dependencies: {', '.join(pypi_pkgs)}")
        _run_pip(pypi_pkgs, quiet=quiet, python=python)
    if nodeps_pkgs:
        _install_pypi_nodeps_packages(
            nodeps_pkgs,
            python=python,
            quiet=quiet,
            bundle_root=bundle_root,
            force=force,
        )
    if spec.torch_package.strip():
        _finalize_torch_cuda_companion_wheels(
            torch_index=torch_index,
            python=python,
            quiet=quiet,
        )

    missing = _missing_runtime_imports(
        spec, python=python, bundle_root=bundle_root
    )
    if missing:
        pip_retry = [
            p
            for p in missing
            if _needs_torch_cuda_wheel_reinstall(
                p,
                python=python,
                bundle_root=bundle_root,
                force=True,
            )
            or (
                not uses_torch_cuda_wheel_index(p)
                and requirement_package_name(p) not in nodeps_names
                and requirement_needs_pip_install(
                    p,
                    python=_pip_python(python),
                    bundle_root=bundle_root,
                    force=True,
                )
            )
        ]
        nodeps_retry = [
            p
            for p in missing
            if requirement_package_name(p) in nodeps_names
            and requirement_needs_pip_install(
                p,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=True,
            )
        ]
        if pip_retry or nodeps_retry:
            if pip_retry:
                if not quiet:
                    print(f"Retrying missing bundle imports: {', '.join(pip_retry)}")
                retry_torch = [p for p in pip_retry if uses_torch_cuda_wheel_index(p)]
                retry_pypi = [
                    p
                    for p in pip_retry
                    if not uses_torch_cuda_wheel_index(p)
                    and requirement_package_name(p) not in nodeps_names
                ]
                if retry_torch:
                    _pip_install_torch_index_packages(
                        retry_torch,
                        torch_index=torch_index,
                        python=python,
                        quiet=quiet,
                    )
                if retry_pypi:
                    _run_pip(retry_pypi, quiet=quiet, python=python)
            if nodeps_retry:
                _install_pypi_nodeps_packages(
                    nodeps_retry,
                    python=python,
                    quiet=quiet,
                    bundle_root=bundle_root,
                    force=True,
                )
            if spec.torch_package.strip():
                _finalize_torch_cuda_companion_wheels(
                    torch_index=torch_index,
                    python=python,
                    quiet=quiet,
                )
        missing = _missing_runtime_imports(
            spec, python=python, bundle_root=bundle_root
        )
    if missing:
        details = ", ".join(
            f"{p} (import {import_name_for_requirement(p)})" for p in missing
        )
        raise RuntimeError(
            f"Bundle Python dependencies still missing after pip install: {details}\n"
            f"Spec source: {spec.source}\n"
            "Try: flashcli bundle install <path>"
        )


def repair_bundle_python_stack(
    *,
    bundle_root: Path,
    torch_index: str = "cu124",
    python: Path | None = None,
    quiet: bool = False,
) -> None:
    ensure_runtime_python_stack(
        bundle_root=bundle_root,
        torch_index=torch_index,
        python=python,
        quiet=quiet,
        force=True,
    )
