"""Load FlashRT runtime Python dependencies from manifest or FlashRT pyproject."""

from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement

_TORCH_NAMES = frozenset({"torch", "pytorch"})
_TORCH_CUDA_WHEEL_NAMES = frozenset({"torchaudio", "torchvision", "torchtext"})

# PyPI name -> importlib module name (when they differ).
_IMPORT_NAMES: dict[str, str] = {
    "pillow": "PIL",
    "pyyaml": "yaml",
    "opencv-python": "cv2",
    "melband-roformer-infer": "mel_band_roformer",
}


@dataclass
class RuntimeRequirementsSpec:
    """Pip requirements for an installed runtime package."""

    pip_packages: list[str] = field(default_factory=list)
    torch_package: str = "torch"
    torch_index: str = ""
    optional_groups: dict[str, list[str]] = field(default_factory=dict)
    source: str = "unknown"

    def pip_packages_for_bundle(self) -> list[str]:
        """Inference-only pip packages declared by the bundle manifest."""
        return _dedupe_strings(list(self.pip_packages))

    def all_packages(self) -> list[str]:
        pkgs = list(self.pip_packages_for_bundle())
        if self.torch_package.strip():
            pkgs.insert(0, self.torch_package)
        return _dedupe_strings(pkgs)


def _load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        import tomli

        return tomli.loads(text)


def _req_name(spec: str) -> str:
    return Requirement(spec).name.lower()


def requirement_package_name(spec: str) -> str:
    """Normalized PyPI distribution name for a pip requirement string."""
    return _req_name(spec)


def declared_package_names(spec: RuntimeRequirementsSpec) -> frozenset[str]:
    """Normalized distribution names declared by the manifest stack."""
    return frozenset(_req_name(pkg) for pkg in spec.all_packages())


def torch_ecosystem_package_names() -> frozenset[str]:
    """Distribution names that must come from the PyTorch CUDA wheel index."""
    return _TORCH_NAMES | _TORCH_CUDA_WHEEL_NAMES


def uses_torch_cuda_wheel_index(spec: str) -> bool:
    """True for packages that must install from the PyTorch CUDA wheel index."""
    return _req_name(spec) in _TORCH_CUDA_WHEEL_NAMES


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = _req_name(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_torch_dependency(value: Any) -> tuple[str, str]:
    """Return ``(pip_package_spec, torch_index)`` from manifest ``python_dependencies.torch``."""
    if value is False or value is None:
        return "", ""
    if isinstance(value, dict):
        pkg = str(value.get("package", "torch")).strip() or "torch"
        idx = str(value.get("index", "")).strip()
        return pkg, idx
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in ("", "skip", "none", "false"):
            return "", ""
        return s or "torch", ""
    s = str(value).strip()
    return (s, "") if s else ("torch", "")


def _torch_package_from_manifest(value: Any) -> str:
    """Return pip torch spec, or empty string to skip torch install (stub bundles)."""
    pkg, _ = parse_torch_dependency(value)
    return pkg


def _split_torch(packages: list[str]) -> tuple[str, list[str]]:
    torch_spec = "torch"
    non_torch: list[str] = []
    for spec in packages:
        if _req_name(spec) in _TORCH_NAMES:
            torch_spec = spec
        else:
            non_torch.append(spec)
    return torch_spec, non_torch


def _runtime_requirements_file(repo_root: Path) -> Path:
    return repo_root / "requirements" / "runtime-inference.txt"


def extract_from_flashrt_pyproject(repo_root: Path) -> RuntimeRequirementsSpec:
    """Read requirements/runtime-inference.txt + ``pyproject.toml`` torch extra."""
    merged: list[str] = []
    req_file = _runtime_requirements_file(repo_root)
    if req_file.is_file():
        merged.extend(_parse_requirements_txt(req_file.read_text(encoding="utf-8")))

    path = repo_root / "pyproject.toml"
    if path.is_file():
        data = _load_toml(path)
        project = data.get("project", {})
        optional = project.get("optional-dependencies", {})
        merged.extend(project.get("dependencies", []))
        merged.extend(optional.get("torch", []))
    elif not merged:
        raise FileNotFoundError(
            f"FlashRT dependencies not found: need {req_file} or {path}"
        )

    merged = _dedupe_strings(merged)

    torch_spec, pip_packages = _split_torch(merged)
    return RuntimeRequirementsSpec(
        pip_packages=pip_packages,
        torch_package=torch_spec,
        optional_groups={
            "server": list(optional.get("server", [])),
        },
        source=f"flashrt-pyproject:{path}",
    )


def _parse_requirements_txt(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _spec_from_python_dependencies(
    py: dict[str, Any],
    *,
    source: str,
    pip_from_txt: list[str] | None = None,
) -> RuntimeRequirementsSpec | None:
    pip = list(py.get("pip", []))
    if pip_from_txt:
        pip.extend(pip_from_txt)
    pip = _dedupe_strings(pip)
    torch_spec, torch_index = parse_torch_dependency(py.get("torch", "torch"))
    optional = py.get("optional_groups", {})
    if isinstance(optional, dict):
        groups = {str(k): list(v) for k, v in optional.items()}
    else:
        groups = {}
    if pip or torch_spec:
        return RuntimeRequirementsSpec(
            pip_packages=pip,
            torch_package=torch_spec,
            torch_index=torch_index,
            optional_groups=groups,
            source=source,
        )
    return None


def load_from_bundle_root(bundle_root: Path) -> RuntimeRequirementsSpec:
    """Load ``python_dependencies`` from ``flashcli-bundle.json``."""
    bundle_root = bundle_root.resolve()
    bundle_json = bundle_root / "flashcli-bundle.json"
    if not bundle_json.is_file():
        raise FileNotFoundError(f"Missing {bundle_json}")

    data = json.loads(bundle_json.read_text(encoding="utf-8"))
    req_path = bundle_root / "requirements-runtime.txt"
    pip_from_txt: list[str] = []
    if req_path.is_file():
        pip_from_txt = _parse_requirements_txt(req_path.read_text(encoding="utf-8"))

    py = data.get("python_dependencies")
    if isinstance(py, dict):
        spec = _spec_from_python_dependencies(
            py,
            source=f"flashcli-bundle.json:{bundle_json}",
            pip_from_txt=pip_from_txt,
        )
        if spec is not None:
            return spec

    if pip_from_txt:
        torch_spec, pip_packages = _split_torch(pip_from_txt)
        return RuntimeRequirementsSpec(
            pip_packages=pip_packages,
            torch_package=torch_spec,
            source=f"requirements-runtime.txt:{req_path}",
        )

    raise FileNotFoundError(
        f"No python_dependencies in {bundle_json} and no requirements-runtime.txt"
    )


def _flashcli_bundled_inference_spec() -> RuntimeRequirementsSpec:
    """Last-resort runtime deps shipped with flashcli (dev bundles without manifest)."""
    flashcli_root = Path(__file__).resolve().parents[3]
    req_file = flashcli_root / "scripts" / "requirements" / "runtime-inference.txt"
    pip_packages: list[str] = []
    if req_file.is_file():
        pip_packages = _parse_requirements_txt(req_file.read_text(encoding="utf-8"))
    if not pip_packages:
        pip_packages = [
            "numpy",
            "pyyaml",
            "safetensors",
            "sentencepiece",
            "ml_dtypes",
            "transformers<4.56",
            "pillow",
        ]
    return RuntimeRequirementsSpec(
        pip_packages=pip_packages,
        torch_package="torch",
        source=f"flashcli-bundled:{req_file}",
    )


def _flashrt_repo_candidates() -> list[Path]:
    flashcli_root = Path(__file__).resolve().parents[3]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for raw in (
        os.environ.get("FLASHRT_REPO_ROOT", "").strip(),
        os.environ.get("FLASHRT_REPO", "").strip(),
    ):
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path not in seen:
            seen.add(path)
            candidates.append(path)
    for path in (
        flashcli_root.parent / "FlashRT",
        flashcli_root.parent,
    ):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)
    return candidates


def resolve_runtime_requirements(
    runtime_dir: Path | None = None,
    *,
    bundle_root: Path | None = None,
) -> RuntimeRequirementsSpec:
    """Load deps from ``flashcli-bundle.json``, else FlashRT source tree fallback."""
    root = bundle_root or runtime_dir
    if root is not None and root.is_dir():
        try:
            return load_from_bundle_root(root)
        except FileNotFoundError:
            pass

    for candidate in _flashrt_repo_candidates():
        if (candidate / "pyproject.toml").is_file() and (candidate / "flash_rt").is_dir():
            try:
                spec = extract_from_flashrt_pyproject(candidate)
                spec.source = f"fallback-pyproject:{candidate}"
                return spec
            except (FileNotFoundError, KeyError, ValueError):
                continue

    return _flashcli_bundled_inference_spec()


def write_runtime_requirements_artifacts(
    stage_dir: Path,
    spec: RuntimeRequirementsSpec,
    *,
    merge_into_manifest: dict | None = None,
) -> None:
    """Write requirements-runtime.txt (author reference only).

    ``merge_into_manifest`` is deprecated: ``flashcli-bundle.json`` is publisher-owned;
    build must not overwrite ``python_dependencies``. See docs/bundle_manifest_policy.md.
    """
    stage_dir = stage_dir.resolve()
    lines = spec.pip_packages_for_bundle()
    (stage_dir / "requirements-runtime.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    if merge_into_manifest is not None:
        warnings.warn(
            "merge_into_manifest is deprecated; maintain python_dependencies in "
            "flashcli-bundle.json instead (see docs/bundle_manifest_policy.md)",
            DeprecationWarning,
            stacklevel=2,
        )
        merge_into_manifest["python_dependencies"] = {
            "torch": spec.torch_package,
            "pip": spec.pip_packages,
        }


def import_name_for_requirement(spec: str) -> str:
    name = _req_name(spec)
    return _IMPORT_NAMES.get(name, re.sub(r"[-.]", "_", name))


def pythonpath_env(bundle_root: Path | None) -> dict[str, str]:
    import os

    env = os.environ.copy()
    if bundle_root is None:
        return env
    root = str(bundle_root.expanduser().resolve())
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + prev if prev else "")
    return env


def requirement_import_satisfied(
    spec: str,
    *,
    python: Path | str,
    bundle_root: Path | None = None,
) -> bool:
    """True when a pip spec is installed in *python* (metadata first, then import)."""
    import subprocess

    mod = import_name_for_requirement(spec)
    py = str(python)
    env = pythonpath_env(bundle_root)

    script = f"""
import importlib.metadata as md
from packaging.requirements import Requirement

spec = {spec!r}
mod = {mod!r}
req = Requirement(spec)

def distribution_ok() -> bool:
    try:
        ver = md.version(req.name)
    except md.PackageNotFoundError:
        return False
    return not req.specifier or ver in req.specifier

# Pip packages may use a different import root than normalized PyPI name
# (e.g. melband-roformer-infer installs import mel_band_roformer).
if distribution_ok():
    raise SystemExit(0)

# Installed but version does not satisfy the specifier → needs pip upgrade.
if req.specifier:
    try:
        md.version(req.name)
    except md.PackageNotFoundError:
        pass
    else:
        raise SystemExit(1)

try:
    __import__(mod)
except ImportError:
    raise SystemExit(1)
raise SystemExit(0)
"""
    proc = subprocess.run(
        [py, "-c", script],
        env=env,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def requirement_needs_pip_install(
    spec: str,
    *,
    python: Path | str,
    bundle_root: Path | None = None,
    force: bool = False,
) -> bool:
    if force:
        return True
    return not requirement_import_satisfied(
        spec, python=python, bundle_root=bundle_root
    )
