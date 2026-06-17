"""Architecture boundary tests — host / protocol / infer / bundle manifest deps."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST_SRC = ROOT / "src" / "flashcli"
FLASHCLI_BUNDLE = ROOT / "flashcli-bundle"


def _read_host_pyproject_deps() -> set[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps: set[str] = set()
    in_deps = False
    for line in text.splitlines():
        if line.strip() == "dependencies = [":
            in_deps = True
            continue
        if in_deps:
            if line.strip() == "]":
                break
            m = re.match(r'\s*"([^"]+)"', line)
            if m:
                deps.add(m.group(1).split(";")[0].strip().lower())
    return deps


def _read_infer_extra() -> set[str]:
    text = (FLASHCLI_BUNDLE / "pyproject.toml").read_text(encoding="utf-8")
    deps: set[str] = set()
    in_infer = False
    for line in text.splitlines():
        if line.strip() == "infer = [":
            in_infer = True
            continue
        if in_infer:
            if line.strip() == "]":
                break
            m = re.match(r'\s*"([^"]+)"', line)
            if m:
                deps.add(m.group(1).split(";")[0].strip().lower())
    return deps


def test_host_pyproject_has_no_serve_stack() -> None:
    host = _read_host_pyproject_deps()
    assert "fastapi>=0.100" not in host
    assert not any(d.startswith("uvicorn") for d in host)
    assert "huggingface_hub>=0.26" in host


def test_protocol_pyproject_has_no_runtime_deps() -> None:
    text = (FLASHCLI_BUNDLE / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text


def test_infer_extra_covers_serve_stack() -> None:
    infer = _read_infer_extra()
    assert any(d.startswith("fastapi") for d in infer)
    assert any(d.startswith("uvicorn") for d in infer)
    assert any(d.startswith("typer") for d in infer)
    assert not any("huggingface" in d for d in infer)


def test_host_deps_constant_matches_pyproject() -> None:
    from flashcli.deps import FLASHCLI_HOST_PACKAGES

    host_toml = _read_host_pyproject_deps()
    for spec in FLASHCLI_HOST_PACKAGES:
        assert spec.lower() in host_toml


def test_host_pyproject_deps_covered_by_auto_install() -> None:
    """Every unconditional host pyproject dep must be in FLASHCLI_HOST_PACKAGES."""
    from flashcli.deps import FLASHCLI_HOST_PACKAGES

    host_toml = _read_host_pyproject_deps()
    auto = {p.split(";")[0].strip().lower() for p in FLASHCLI_HOST_PACKAGES}
    for spec in host_toml:
        if spec.startswith("tomli"):
            continue  # stdlib tomllib on 3.11+; conditional in pyproject only
        assert spec in auto, f"pyproject dep {spec!r} missing from FLASHCLI_HOST_PACKAGES"

def test_host_tree_never_imports_infer() -> None:
    forbidden = "flashcli_bundle.infer"
    offenders: list[str] = []
    for path in HOST_SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                        offenders.append(f"{path.relative_to(HOST_SRC)}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and (
                    node.module == forbidden or node.module.startswith(forbidden + ".")
                ):
                    offenders.append(f"{path.relative_to(HOST_SRC)}: from {node.module}")
    assert not offenders, "\n".join(offenders)


def test_infer_bundle_subpackage_has_no_duplicate_protocol_stubs() -> None:
    """Protocol modules must live under flashcli_bundle/, not infer/bundle/ stubs."""
    stub_names = {
        "layout.py",
        "catalog.py",
        "manifest_ext.py",
        "native.py",
        "variants.py",
    }
    bundle_dir = FLASHCLI_BUNDLE / "src" / "flashcli_bundle" / "infer" / "bundle"
    present = {p.name for p in bundle_dir.glob("*.py")}
    assert not stub_names & present, f"Remove duplicate stubs: {stub_names & present}"


def test_protocol_import_without_pip_extras() -> None:
    import flashcli_bundle.manifest
    import flashcli_bundle.manifest_ext
    import flashcli_bundle.paths
    import flashcli_bundle.runtime.detect

    assert flashcli_bundle.manifest.BundleManifest is not None
    assert flashcli_bundle.paths.CACHE_DIR == flashcli_bundle.paths.FLASHCLI_HOME / "cache" / "downloads"


def test_host_config_reexports_protocol_paths() -> None:
    import flashcli.config as host_config
    import flashcli_bundle.paths as paths

    assert host_config.FLASHCLI_HOME is paths.FLASHCLI_HOME
    assert host_config.BUNDLES_DIR is paths.BUNDLES_DIR
    assert host_config.CACHE_DIR is paths.CACHE_DIR


def test_host_config_defines_paths_once() -> None:
    """Host config must not duplicate path constant definitions."""
    text = (HOST_SRC / "config.py").read_text(encoding="utf-8")
    assert "os.environ.get(\"FLASHCLI_HOME\"" not in text
    assert "from flashcli_bundle.paths import" in text


@pytest.mark.parametrize(
    "rel",
    [
        "src/flashcli/serve",
        "src/flashcli/engines",
        "src/flashcli/bundle/bundle_options.py",
    ],
)
def test_removed_host_infer_shims_absent(rel: str) -> None:
    path = ROOT / rel
    assert not path.exists(), f"Obsolete host shim still present: {rel}"
