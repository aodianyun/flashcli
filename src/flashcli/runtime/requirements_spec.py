"""Load FlashRT runtime Python dependencies from manifest or FlashRT pyproject."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement

_TORCH_NAMES = frozenset({"torch", "pytorch"})

# PyPI name -> importlib module name (when they differ).
_IMPORT_NAMES: dict[str, str] = {
    "pillow": "PIL",
    "pyyaml": "yaml",
    "opencv-python": "cv2",
}


@dataclass
class RuntimeRequirementsSpec:
    """Pip requirements for an installed runtime package."""

    pip_packages: list[str] = field(default_factory=list)
    torch_package: str = "torch"
    optional_groups: dict[str, list[str]] = field(default_factory=dict)
    source: str = "unknown"

    def packages_for_profile(self, profile: str = "default") -> list[str]:
        pkgs = list(self.pip_packages)
        if profile == "serve":
            pkgs.extend(self.optional_groups.get("server", []))
        return _dedupe_strings(pkgs)

    def all_packages_for_profile(self, profile: str = "default") -> list[str]:
        pkgs = list(self.packages_for_profile(profile))
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


def _torch_package_from_manifest(value: Any) -> str:
    """Return pip torch spec, or empty string to skip torch install (stub bundles)."""
    if value is False or value is None:
        return ""
    if isinstance(value, str) and value.strip().lower() in ("", "skip", "none", "false"):
        return ""
    return str(value).strip() or "torch"


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


def load_from_runtime_dir(runtime_dir: Path) -> RuntimeRequirementsSpec:
    """Load spec bundled inside an installed runtime package."""
    runtime_dir = runtime_dir.resolve()
    manifest_path = runtime_dir / "manifest.json"
    req_path = runtime_dir / "requirements-runtime.txt"

    pip_from_txt: list[str] = []
    if req_path.is_file():
        pip_from_txt = _parse_requirements_txt(req_path.read_text(encoding="utf-8"))

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        py = manifest.get("python_dependencies")
        if isinstance(py, dict):
            pip = list(py.get("pip", []))
            pip.extend(pip_from_txt)
            pip = _dedupe_strings(pip)
            torch_spec = _torch_package_from_manifest(py.get("torch", "torch"))
            optional = py.get("optional_groups", {})
            if isinstance(optional, dict):
                groups = {str(k): list(v) for k, v in optional.items()}
            else:
                groups = {}
            if pip or torch_spec:
                return RuntimeRequirementsSpec(
                    pip_packages=pip,
                    torch_package=torch_spec,
                    optional_groups=groups,
                    source=f"manifest:{manifest_path}",
                )

    if pip_from_txt:
        torch_spec, pip_packages = _split_torch(pip_from_txt)
        return RuntimeRequirementsSpec(
            pip_packages=pip_packages,
            torch_package=torch_spec,
            source=f"requirements-runtime.txt:{req_path}",
        )

    raise FileNotFoundError(
        f"No python_dependencies in manifest and no requirements-runtime.txt under {runtime_dir}"
    )


def resolve_runtime_requirements(runtime_dir: Path | None = None) -> RuntimeRequirementsSpec:
    """Runtime bundle first; else FlashRT source tree for dev/legacy packages."""
    if runtime_dir is not None and runtime_dir.is_dir():
        try:
            return load_from_runtime_dir(runtime_dir)
        except FileNotFoundError:
            pass

    env_root = os.environ.get("FLASHRT_REPO_ROOT", "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    # flashcli lives at <FlashRT>/flashcli/
    flashcli_pkg = Path(__file__).resolve().parents[3]
    candidates.append(flashcli_pkg.parent)

    for root in candidates:
        if (root / "pyproject.toml").is_file() and (root / "flash_rt").is_dir():
            try:
                spec = extract_from_flashrt_pyproject(root)
                spec.source = f"fallback-pyproject:{root}"
                return spec
            except (FileNotFoundError, KeyError, ValueError):
                continue

    raise RuntimeError(
        "Cannot resolve FlashRT runtime Python dependencies. "
        "Rebuild the model bundle (flashcli/scripts/build_*_bundle.sh) so it includes "
        "manifest python_dependencies / requirements-runtime.txt, or set FLASHRT_REPO_ROOT."
    )


def write_runtime_requirements_artifacts(
    stage_dir: Path,
    spec: RuntimeRequirementsSpec,
    *,
    merge_into_manifest: dict | None = None,
) -> None:
    """Write requirements-runtime.txt and optional manifest fields."""
    stage_dir = stage_dir.resolve()
    lines = spec.packages_for_profile("default")
    (stage_dir / "requirements-runtime.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    if merge_into_manifest is not None:
        merge_into_manifest["python_dependencies"] = {
            "torch": spec.torch_package,
            "pip": spec.pip_packages,
            "optional_groups": spec.optional_groups,
        }


def import_name_for_requirement(spec: str) -> str:
    name = _req_name(spec)
    return _IMPORT_NAMES.get(name, re.sub(r"[-.]", "_", name))
