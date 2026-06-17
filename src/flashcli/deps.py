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
    requirement_import_satisfied,
    requirement_needs_pip_install,
    resolve_runtime_requirements,
)

FLASHCLI_HOST_PACKAGES = [
    # Host CLI only (pull, Hub CLI, sync). Serve HTTP stack lives in bundle venv [infer].
    "typer>=0.12",
    "pyyaml>=6.0",
    "packaging>=23.0",
    "huggingface_hub>=0.26",
    "tqdm>=4.66",
]


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


def _missing_imports(packages: list[str], *, python: Path | None = None) -> list[str]:
    return [p for p in packages if not _imports_ok(p, python=python)]


def _missing_runtime_imports(
    spec: RuntimeRequirementsSpec,
    *,
    python: Path | None = None,
    bundle_root: Path | None = None,
) -> list[str]:
    missing: list[str] = []
    for pkg in spec.all_packages():
        if not _imports_ok(pkg, python=python, bundle_root=bundle_root):
            missing.append(pkg)
    return missing


def flashcli_core_stack_satisfied() -> bool:
    return not _missing_imports(FLASHCLI_HOST_PACKAGES)


def flashcli_stack_satisfied() -> bool:
    return flashcli_core_stack_satisfied()


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
) -> None:
    cmd = [_pip_python(python), "-m", "pip", "install"]
    if use_pypi_mirror:
        cmd.extend(pip_install_extra_args())
    cmd.extend(args)
    if quiet:
        cmd.append("-q")
    subprocess.run(cmd, check=True)


def ensure_flashcli_core_stack(*, quiet: bool = False, force: bool = False) -> None:
    """Install host CLI pip deps and ``flashcli-bundle`` (protocol only)."""
    to_install = [p for p in FLASHCLI_HOST_PACKAGES if force or not _imports_ok(p)]
    if to_install:
        if not quiet:
            print(f"Installing flashcli host dependencies: {', '.join(to_install)}")
        _run_pip(to_install, quiet=quiet)
    host_py = Path(sys.executable)
    if force or not _module_available("flashcli_bundle", python=host_py):
        ensure_flashcli_bundle_in_venv(
            python=host_py, quiet=quiet, force=force, extras=()
        )


def ensure_bundle_infer_deps(
    *,
    python: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Install ``flashcli-bundle[infer]`` into the bundle venv interpreter."""
    if python is None:
        raise ValueError("python is required for ensure_bundle_infer_deps")
    ensure_flashcli_bundle_in_venv(
        python=python, quiet=quiet, force=force, extras=("infer",)
    )


def ensure_flashcli_stack(*, quiet: bool = False, force: bool = False) -> None:
    ensure_flashcli_core_stack(quiet=quiet, force=force)


def ensure_runtime_python_stack(
    *,
    bundle_root: Path | None = None,
    torch_index: str = "cu124",
    python: Path | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    """pip install bundle inference stack into the bundle venv interpreter."""
    if bundle_root is None:
        raise ValueError("bundle_root is required")
    if python is not None:
        ensure_flashcli_bundle_in_venv(
            python=python, quiet=quiet, force=force, extras=("infer",)
        )
    spec = resolve_runtime_requirements(bundle_root=bundle_root)

    if not force and not _missing_runtime_imports(
        spec, python=python, bundle_root=bundle_root
    ):
        return

    if not quiet:
        print(f"Installing bundle Python dependencies from: {spec.source}")

    if spec.torch_package.strip():
        index_url = resolve_torch_index_url(torch_index)
        if (
            requirement_needs_pip_install(
                spec.torch_package,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=force,
            )
        ):
            if not quiet:
                print(f"Installing {spec.torch_package} from {index_url} ...")
            torch_args = [spec.torch_package, "--index-url", index_url]
            pypi = pip_index_url()
            if pypi:
                torch_args.extend(["--extra-index-url", pypi])
                host = pip_trusted_host()
                if host:
                    torch_args.extend(["--trusted-host", host])
            _run_pip(torch_args, quiet=quiet, use_pypi_mirror=False, python=python)

    to_install = [
        p
        for p in spec.pip_packages
        if requirement_needs_pip_install(
            p,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        )
    ]

    if to_install:
        if not quiet:
            print(f"Installing bundle runtime dependencies: {', '.join(to_install)}")
        _run_pip(to_install, quiet=quiet, python=python)

    missing = _missing_runtime_imports(
        spec, python=python, bundle_root=bundle_root
    )
    if missing:
        pip_retry = [
            p
            for p in missing
            if requirement_needs_pip_install(
                p,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=True,
            )
        ]
        if pip_retry:
            if not quiet:
                print(f"Retrying missing bundle imports: {', '.join(pip_retry)}")
            _run_pip(pip_retry, quiet=quiet, python=python)
        missing = _missing_runtime_imports(
            spec, python=python, bundle_root=bundle_root
        )
    if missing:
        names = ", ".join(import_name_for_requirement(p) for p in missing)
        raise RuntimeError(
            f"Bundle Python dependencies still missing after pip install: {names}\n"
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


def _load_persisted_install_env() -> None:
    """Apply ``~/.flashcli/install.env`` (written by ``install.sh``) if present."""
    import os

    from flashcli import config

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
) -> str | None:
    """Rebuild a pip git/editable spec from ``direct_url.json`` (git installs)."""
    import json

    try:
        from importlib.metadata import distribution

        data = json.loads(distribution(dist_name).read_text("direct_url.json"))
    except (ImportError, OSError, KeyError, TypeError, json.JSONDecodeError):
        return None

    pkg = dist_name.replace("_", "-")
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
        return f"{pkg} @ {spec}"

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


def flashcli_bundle_pip_spec(*, extras: tuple[str, ...] = ()) -> str:
    """Pip spec for installing ``flashcli-bundle`` into a bundle venv."""
    import os

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

    spec = _pip_spec_from_direct_url("flashcli-bundle")
    if spec and extras:
        if spec.startswith("flashcli-bundle @ "):
            return f"flashcli-bundle{extra_suffix} @ " + spec.split(" @ ", 1)[1]
    if spec:
        return spec

    spec = _pip_spec_from_direct_url("flashcli", subdirectory="flashcli-bundle")
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


def _infer_module_available(*, python: Path) -> bool:
    proc = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util; "
            "raise SystemExit(0 if importlib.util.find_spec('flashcli_bundle.infer') else 1)",
        ],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def ensure_flashcli_bundle_in_venv(
    *,
    python: Path,
    quiet: bool = False,
    force: bool = False,
    extras: tuple[str, ...] = ("infer",),
) -> None:
    """Install ``flashcli-bundle`` (and optional extras) into the bundle venv."""
    want_infer = "infer" in extras
    if not force:
        if want_infer and _infer_module_available(python=python):
            return
        if not want_infer and _module_available("flashcli_bundle", python=python):
            return
    spec = flashcli_bundle_pip_spec(extras=extras)
    extra_label = f"[{','.join(extras)}]" if extras else ""
    if not quiet:
        print(f"Installing flashcli-bundle{extra_label} into bundle venv ({spec}) ...")
    if " @ " not in spec:
        _run_pip(["-e", spec], quiet=quiet, python=python)
    else:
        _run_pip([spec], quiet=quiet, python=python)
