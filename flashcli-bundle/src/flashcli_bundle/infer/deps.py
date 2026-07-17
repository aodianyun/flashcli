"""Install bundle inference dependencies into the bundle venv.

Flow (host ``pull`` / ``activate_bundle``):
  1. ``resolve_runtime_requirements(bundle_root)`` — manifest ``python_dependencies``
  2. ``ensure_flashcli_bundle_in_venv`` — ``flashcli-bundle[infer]`` only (never host ``flashcli``)
  3. ``_install_runtime_batches`` — torch CUDA index → pin constraints → PyPI / isolated / VCS
  4. ``requirement_import_satisfied`` (protocol) — venv metadata + ``find_spec``, ``python -I``

See ``docs/architecture.zh-CN.md`` (bundle venv pip layers) and ``module_layers.zh-CN.md``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email import message_from_string
from pathlib import Path

from flashcli_bundle import paths as config
from flashcli_bundle.infer.runtime.mirror import (
    apply_mirror_env,
    default_pip_index_url,
    pip_install_extra_args,
    pip_trusted_host,
    resolve_torch_index_url,
)
from flashcli_bundle.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    import_name_for_requirement,
    requirement_import_failure_reason,
    requirement_import_satisfied,
    requirement_needs_pip_install,
    requirement_package_name,
    resolve_runtime_requirements,
    torch_ecosystem_package_names,
    uses_torch_cuda_wheel_index,
    venv_purelib,
)

_INFER_EXTRA = "infer"
_TORCH_CONSTRAINTS_BASENAME = "torch-ecosystem.constraints.txt"


def _venv_root_from_python(python: Path) -> Path:
    parent = python.resolve().parent
    if parent.name in ("bin", "Scripts"):
        return parent.parent
    return parent


def torch_ecosystem_constraints_path(python: Path) -> Path:
    """Path to pip constraints pinning installed torch-ecosystem wheels in a bundle venv."""
    return _venv_root_from_python(python) / _TORCH_CONSTRAINTS_BASENAME


def format_torch_ecosystem_constraint_lines(installed_versions: dict[str, str]) -> list[str]:
    """Build ``pip --constraint`` lines (exact versions including ``+cu128`` locals)."""
    return [f"{name}=={version}" for name, version in sorted(installed_versions.items())]


_HOST_MANAGED_PIP_NAMES = frozenset({"flashcli-bundle"})


def _host_managed_pip_package(spec: str) -> bool:
    return requirement_package_name(spec) in _HOST_MANAGED_PIP_NAMES


def _pip_show_version(*, python: Path, name: str) -> str | None:
    proc = subprocess.run(
        [str(python), "-m", "pip", "show", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    version: str | None = None
    location: Path | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("Version:"):
            version = line.partition(":")[2].strip() or None
        elif line.startswith("Location:"):
            location = Path(line.partition(":")[2].strip())
    if not version:
        return None
    site = venv_purelib(python)
    if site is None or location is None:
        return None
    try:
        location.resolve().relative_to(site.resolve())
    except ValueError:
        return None
    return version


def _query_installed_torch_ecosystem_versions(*, python: Path) -> dict[str, str]:
    """Versions pip actually installed in the bundle venv (not importlib metadata)."""
    py = python.resolve()
    out: dict[str, str] = {}
    for name in sorted(torch_ecosystem_package_names()):
        if name == "pytorch" and "torch" in out:
            continue
        version = _pip_show_version(python=py, name=name)
        if version:
            out[name] = version
    return out


def _refresh_torch_ecosystem_constraints(
    *,
    python: Path | None,
    quiet: bool,
) -> Path | None:
    """Pin installed torch/torchaudio/... so later PyPI installs cannot replace CUDA builds."""
    if python is None:
        return None
    py = python.resolve()
    installed = _query_installed_torch_ecosystem_versions(python=py)
    if not installed:
        return None
    path = torch_ecosystem_constraints_path(py)
    lines = format_torch_ecosystem_constraint_lines(installed)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not quiet:
        print(f"Pinned torch stack in {path.name}: {', '.join(lines)}")
    return path


def _constraints_for_pypi_install(*, python: Path | None) -> Path | None:
    if python is None:
        return None
    path = torch_ecosystem_constraints_path(python.resolve())
    return path if path.is_file() else None


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


def _torch_wheel_cuda_probe(import_name: str) -> str:
    return f"""
import torch
try:
    __import__({import_name!r})
except ImportError:
    raise SystemExit(1)
except RuntimeError as exc:
    msg = str(exc)
    if "different CUDA versions" in msg or "compiled with different CUDA versions" in msg:
        raise SystemExit(1) from exc
    raise
raise SystemExit(0)
"""


def _torch_wheel_cuda_ok(spec: str, *, python: Path | None = None) -> bool:
    """True when a declared torch CUDA wheel import matches torch's CUDA userland."""
    if not uses_torch_cuda_wheel_index(spec):
        return True
    mod = import_name_for_requirement(spec)
    py = _pip_python(python)
    proc = subprocess.run(
        [py, "-c", _torch_wheel_cuda_probe(mod)],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


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
            continue
        if uses_torch_cuda_wheel_index(pkg) and not _torch_wheel_cuda_ok(
            pkg, python=python
        ):
            missing.append(pkg)
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
    constraints: Path | None = None,
) -> None:
    cmd = [_pip_python(python), "-m", "pip", "install"]
    if no_deps:
        cmd.append("--no-deps")
    if constraints is not None and constraints.is_file():
        cmd.extend(["--constraint", str(constraints)])
    if use_pypi_mirror:
        cmd.extend(pip_install_extra_args())
    cmd.extend(args)
    if quiet:
        cmd.append("-q")
    subprocess.run(cmd, check=True)


def _is_vcs_pip_spec(spec: str) -> bool:
    return " @ git+" in spec.lower()


def _parse_vcs_pip_spec(spec: str) -> tuple[str, str, str]:
    """Return ``(distribution_name, repo_url, git_ref)`` from a VCS pip spec."""
    dist, _, rest = spec.partition(" @ git+")
    repo_url, _, ref = rest.rpartition("@")
    if not repo_url or not ref:
        raise ValueError(f"Invalid VCS pip spec: {spec!r}")
    return dist.strip(), repo_url.strip(), ref.strip()


def _is_isaac_gr00t_vcs_spec(spec: str) -> bool:
    if not _is_vcs_pip_spec(spec):
        return False
    _, repo_url, _ = _parse_vcs_pip_spec(spec)
    normalized = repo_url.rstrip("/").lower()
    return normalized.endswith("nvidia/isaac-gr00t.git")


def _git_clone_url(repo_url: str) -> str:
    """Optional GitHub proxy prefix (``FLASHCLI_GIT_PROXY``).

    Only rewrite ``github.com`` / ``codeload.github.com`` URLs. Gitee and already
    proxied URLs are left unchanged.
    """
    proxy = (os.environ.get("FLASHCLI_GIT_PROXY") or "").strip().rstrip("/")
    if not proxy or proxy.lower() in ("0", "false", "no", "off", "auto"):
        return repo_url
    if repo_url.startswith(proxy + "/"):
        return repo_url
    lower = repo_url.lower()
    if "github.com/" not in lower and "codeload.github.com/" not in lower:
        return repo_url
    return f"{proxy}/{repo_url}"


def _apply_git_proxy_to_vcs_spec(spec: str) -> str:
    """Rewrite ``pkg @ git+https://github.com/...@ref#...`` through ``FLASHCLI_GIT_PROXY``."""
    marker = " @ git+"
    lower = spec.lower()
    idx = lower.find(marker)
    if idx < 0:
        return spec
    prefix = spec[:idx]
    vcs = spec[idx + len(marker) :]
    main, frag_sep, frag = vcs.partition("#")
    repo, at, ref = main.rpartition("@")
    if not at or not repo or not ref:
        return spec
    proxied = _git_clone_url(repo)
    if proxied == repo:
        return spec
    out = f"{prefix}{marker}{proxied}@{ref}"
    if frag_sep:
        out += f"#{frag}"
    return out


def _isaac_gr00t_source_dir(git_ref: str) -> Path:
    safe_ref = re.sub(r"[^A-Za-z0-9._-]+", "_", git_ref)
    return config.FLASHCLI_HOME / "cache" / "isaac-gr00t-src" / safe_ref


def _ensure_isaac_gr00t_source(repo_url: str, git_ref: str, *, quiet: bool) -> Path:
    """Shallow clone Isaac-GR00T without submodules (inference-only subset)."""
    local = os.environ.get("FLASHCLI_GR00T_SRC", "").strip()
    if local:
        path = Path(local).expanduser().resolve()
        if not path.is_dir():
            raise RuntimeError(f"FLASHCLI_GR00T_SRC is not a directory: {path}")
        if not (path / "gr00t").is_dir():
            raise RuntimeError(
                f"FLASHCLI_GR00T_SRC must be an Isaac-GR00T checkout with gr00t/: {path}"
            )
        return path

    dest = _isaac_gr00t_source_dir(git_ref)
    if (dest / "pyproject.toml").is_file() and (dest / "gr00t").is_dir():
        return dest

    clone_url = _git_clone_url(repo_url)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(
            f"Cloning Isaac-GR00T ref {git_ref} without submodules "
            f"(cache: {dest}) ..."
        )
    subprocess.run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-recurse-submodules",
            "--depth",
            "1",
            clone_url,
            str(dest),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", git_ref],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", "FETCH_HEAD"],
        check=True,
    )
    return dest


def _install_isaac_gr00t_vcs_package(
    spec: str,
    *,
    python: Path | None,
    quiet: bool,
    constraints: Path | None,
    bundle_root: Path | None,
    force: bool,
) -> None:
    if not force and not requirement_needs_pip_install(
        spec,
        python=_pip_python(python),
        bundle_root=bundle_root,
        force=False,
    ):
        return
    _, repo_url, git_ref = _parse_vcs_pip_spec(spec)
    src = _ensure_isaac_gr00t_source(repo_url, git_ref, quiet=quiet)
    if not quiet:
        print(
            f"Installing gr00t editable from {src} "
            f"(inference-only checkout; simulation submodules skipped)"
        )
    _run_pip(
        ["-e", str(src)],
        quiet=quiet,
        python=python,
        constraints=constraints,
        no_deps=True,
    )


def _torch_index_pip_args(
    packages: list[str],
    torch_index: str,
) -> list[str]:
    """Install torch CUDA wheels: PyPI (or mirror) primary, PyTorch index extra.

    Using the PyTorch index as ``--index-url`` breaks transitive deps (e.g.
    ``typing-extensions``, ``jinja2``) because those wheels have inconsistent
    ``Name`` metadata on download.pytorch.org.
    """
    torch_url = resolve_torch_index_url(torch_index)
    pypi = default_pip_index_url()
    args = list(packages)
    args.extend(["--index-url", pypi])
    host = pip_trusted_host()
    if host:
        args.extend(["--trusted-host", host])
    args.extend(["--extra-index-url", torch_url])
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


def _wheel_requires_dist(
    package_spec: str,
    *,
    python: Path | None = None,
    quiet: bool,
) -> list[str]:
    """Return ``Requires-Dist`` strings from a PyPI wheel (``pip download --no-deps``)."""
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
    out: list[str] = []
    seen: set[str] = set()
    for raw in meta.get_all("Requires-Dist") or []:
        req = Requirement(str(raw))
        name = req.name.lower()
        if name in seen:
            continue
        seen.add(name)
        out.append(str(req))
    return out


def torch_ecosystem_nodeps_needed(
    wheel_requires: list[str],
    covered_ecosystem: frozenset[str],
) -> bool:
    """True when wheel torch-ecosystem requires are covered by the torch-index batch."""
    ecosystem = torch_ecosystem_package_names()
    torch_requires = [
        req for req in wheel_requires if requirement_package_name(req) in ecosystem
    ]
    if not torch_requires:
        return False
    return all(
        requirement_package_name(req) in covered_ecosystem for req in torch_requires
    )


def resolve_torch_index_specs(
    spec: RuntimeRequirementsSpec,
    wheel_requires_by_package: dict[str, list[str]],
) -> tuple[list[str], frozenset[str]]:
    """Manifest torch stack plus torch-ecosystem wheels inferred from PyPI package metadata."""
    ecosystem = torch_ecosystem_package_names()
    ordered: list[str] = []
    seen: set[str] = set()

    def add(spec_str: str) -> None:
        name = requirement_package_name(spec_str)
        if name in seen:
            return
        seen.add(name)
        ordered.append(spec_str)

    if spec.torch_package.strip():
        add(spec.torch_package)

    for pkg in spec.pip_packages:
        if uses_torch_cuda_wheel_index(pkg):
            add(pkg)

    for requires in wheel_requires_by_package.values():
        for req in requires:
            if requirement_package_name(req) in ecosystem:
                add(requirement_package_name(req))

    covered = frozenset(
        requirement_package_name(item)
        for item in ordered
        if requirement_package_name(item) in ecosystem
    )
    return ordered, covered


def _pip_wheel_requires_cache(
    pip_packages: list[str],
    *,
    python: Path | None,
    quiet: bool,
) -> dict[str, list[str]]:
    cache: dict[str, list[str]] = {}
    for pkg in pip_packages:
        if uses_torch_cuda_wheel_index(pkg):
            continue
        if _host_managed_pip_package(pkg):
            continue
        if _is_isaac_gr00t_vcs_spec(pkg):
            continue
        try:
            cache[pkg] = _wheel_requires_dist(pkg, python=python, quiet=quiet)
        except subprocess.CalledProcessError:
            cache[pkg] = []
    return cache


def _needs_torch_index_install(
    spec_str: str,
    *,
    python: Path | None,
    bundle_root: Path | None,
    force: bool,
) -> bool:
    name = requirement_package_name(spec_str)
    if name in {"torch", "pytorch"}:
        return requirement_needs_pip_install(
            spec_str,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        )
    if uses_torch_cuda_wheel_index(spec_str):
        return _needs_torch_cuda_wheel_reinstall(
            spec_str,
            python=python,
            bundle_root=bundle_root,
            force=force,
        ) or requirement_needs_pip_install(
            spec_str,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        )
    return False


def _should_install_without_deps(
    wheel_requires: list[str],
    covered_ecosystem: frozenset[str],
) -> bool:
    """Skip transitive install when the torch-index batch already covers this wheel."""
    return torch_ecosystem_nodeps_needed(wheel_requires, covered_ecosystem)


def pypi_prereqs_for_isolated_install(wheel_requires: list[str]) -> list[str]:
    """Direct PyPI prerequisites for a ``--no-deps`` install (torch stack excluded)."""
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    env = default_environment()
    ecosystem = torch_ecosystem_package_names()
    out: list[str] = []
    seen: set[str] = set()
    for raw in wheel_requires:
        req = Requirement(raw)
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        name = req.name.lower()
        if name in ecosystem:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(str(req))
    return out


def _install_isolated_packages(
    packages: list[str],
    *,
    wheel_cache: dict[str, list[str]],
    python: Path | None = None,
    quiet: bool,
    bundle_root: Path | None,
    force: bool,
) -> None:
    for package_spec in packages:
        prereqs = pypi_prereqs_for_isolated_install(
            wheel_cache.get(package_spec, [])
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
            _run_pip(
                needed_prereqs,
                quiet=quiet,
                python=python,
            )
        if not requirement_needs_pip_install(
            package_spec,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        ):
            continue
        if not quiet:
            print(
                f"Installing {package_spec} (--no-deps; torch stack already installed)"
            )
        _run_pip(
            [package_spec],
            quiet=quiet,
            python=python,
            no_deps=True,
        )


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
    return not _torch_wheel_cuda_ok(spec, python=python)


def _collect_install_batches(
    spec: RuntimeRequirementsSpec,
    *,
    python: Path | None,
    bundle_root: Path | None,
    force: bool,
    quiet: bool,
) -> tuple[list[str], list[str], list[str], dict[str, list[str]], list[str]]:
    wheel_cache = _pip_wheel_requires_cache(
        spec.pip_packages, python=python, quiet=quiet
    )
    torch_specs, covered_ecosystem = resolve_torch_index_specs(spec, wheel_cache)
    torch_index_pkgs = [
        pkg
        for pkg in torch_specs
        if _needs_torch_index_install(
            pkg,
            python=python,
            bundle_root=bundle_root,
            force=force,
        )
    ]

    pypi_pkgs: list[str] = []
    isolated_pkgs: list[str] = []
    vcs_pkgs: list[str] = []
    for pkg in spec.pip_packages:
        if _is_isaac_gr00t_vcs_spec(pkg):
            if requirement_needs_pip_install(
                pkg,
                python=_pip_python(python),
                bundle_root=bundle_root,
                force=force,
            ):
                vcs_pkgs.append(pkg)
            continue
        if uses_torch_cuda_wheel_index(pkg):
            continue
        if _host_managed_pip_package(pkg):
            continue
        if not requirement_needs_pip_install(
            pkg,
            python=_pip_python(python),
            bundle_root=bundle_root,
            force=force,
        ):
            continue
        wheel_requires = wheel_cache.get(pkg, [])
        if _should_install_without_deps(wheel_requires, covered_ecosystem):
            isolated_pkgs.append(pkg)
        else:
            pypi_pkgs.append(pkg)

    return torch_index_pkgs, pypi_pkgs, isolated_pkgs, wheel_cache, vcs_pkgs


def _install_runtime_batches(
    *,
    torch_index_pkgs: list[str],
    pypi_pkgs: list[str],
    isolated_pkgs: list[str],
    vcs_pkgs: list[str],
    wheel_cache: dict[str, list[str]],
    torch_index: str,
    python: Path | None,
    quiet: bool,
    bundle_root: Path | None,
    force: bool,
    force_torch_reinstall: bool = False,
) -> None:
    constraints: Path | None = None
    if torch_index_pkgs:
        _pip_install_torch_index_packages(
            torch_index_pkgs,
            torch_index=torch_index,
            python=python,
            quiet=quiet,
            force_reinstall=force_torch_reinstall,
        )
        if python is not None:
            constraints = _refresh_torch_ecosystem_constraints(
                python=python, quiet=quiet
            )
    if constraints is None and python is not None:
        constraints = _constraints_for_pypi_install(python=python)
    if pypi_pkgs:
        if not quiet:
            print(f"Installing bundle runtime dependencies: {', '.join(pypi_pkgs)}")
        _run_pip(pypi_pkgs, quiet=quiet, python=python, constraints=constraints)
    if isolated_pkgs:
        _install_isolated_packages(
            isolated_pkgs,
            wheel_cache=wheel_cache,
            python=python,
            quiet=quiet,
            bundle_root=bundle_root,
            force=force,
        )
    for vcs_spec in vcs_pkgs:
        _install_isaac_gr00t_vcs_package(
            vcs_spec,
            python=python,
            quiet=quiet,
            constraints=constraints,
            bundle_root=bundle_root,
            force=force,
        )


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
    apply_mirror_env()

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

    # Prefer install.sh source (Gitee / proxied GitHub) over host package direct_url,
    # which often still points at raw github.com even after a mirrored install.
    repo = os.environ.get("FLASHCLI_INSTALL_REPO", "").strip()
    ref = os.environ.get("FLASHCLI_INSTALL_REF", "main").strip() or "main"
    if repo:
        return (
            f"flashcli-bundle{extra_suffix} @ git+{_git_clone_url(repo)}"
            f"@{ref}#subdirectory=flashcli-bundle"
        )

    spec = _pip_spec_from_direct_url("flashcli-bundle", extras=extras)
    if spec:
        return _apply_git_proxy_to_vcs_spec(spec)

    spec = _pip_spec_from_direct_url("flashcli", subdirectory="flashcli-bundle", extras=extras)
    if spec:
        if spec.startswith("flashcli @ "):
            spec = f"flashcli-bundle{extra_suffix} @ " + spec.split(" @ ", 1)[1]
        return _apply_git_proxy_to_vcs_spec(spec)

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


def _install_missing_packages(
    missing: list[str],
    *,
    python: Path | None,
    quiet: bool,
) -> None:
    """Install each missing spec individually (batch resolver can skip stragglers)."""
    if not missing:
        return
    constraints = _constraints_for_pypi_install(python=python)
    for spec in missing:
        if not quiet:
            print(f"Installing missing bundle dependency: {spec}")
        _run_pip([spec], quiet=quiet, python=python, constraints=constraints)


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

    torch_index_pkgs, pypi_pkgs, isolated_pkgs, wheel_cache, vcs_pkgs = _collect_install_batches(
        spec,
        python=python,
        bundle_root=bundle_root,
        force=force,
        quiet=quiet,
    )
    _install_runtime_batches(
        torch_index_pkgs=torch_index_pkgs,
        pypi_pkgs=pypi_pkgs,
        isolated_pkgs=isolated_pkgs,
        vcs_pkgs=vcs_pkgs,
        wheel_cache=wheel_cache,
        torch_index=torch_index,
        python=python,
        quiet=quiet,
        bundle_root=bundle_root,
        force=force,
    )

    missing = _missing_runtime_imports(
        spec, python=python, bundle_root=bundle_root
    )
    if missing:
        _install_missing_packages(missing, python=python, quiet=quiet)
        missing = _missing_runtime_imports(
            spec, python=python, bundle_root=bundle_root
        )
    if missing:
        py = _pip_python(python)
        detail_lines: list[str] = []
        for pkg in missing:
            line = f"{pkg} (import {import_name_for_requirement(pkg)})"
            reason = requirement_import_failure_reason(
                pkg, python=py, bundle_root=bundle_root
            )
            if reason:
                line = f"{line}: {reason}"
            detail_lines.append(line)
        details = "; ".join(detail_lines)
        hint = (
            "Probes use the bundle venv with python -I (no host PYTHONPATH). "
            "If a package is listed in flashcli-bundle.json but still fails, "
            "check pip install output above or retry after removing the runtime venv."
        )
        raise RuntimeError(
            f"Bundle Python dependencies still missing after pip install: {details}\n"
            f"Spec source: {spec.source}\n"
            f"{hint}\n"
            "Declare every runtime dependency in flashcli-bundle.json python_dependencies."
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
