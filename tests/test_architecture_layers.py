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


def test_run_help_module_uses_protocol_only() -> None:
    text = (HOST_SRC / "bundle" / "run_help.py").read_text(encoding="utf-8")
    assert "flashcli_bundle.infer" not in text
    assert "flashcli_bundle.manifest_resolve" in text
    assert "flashcli_bundle.help_text" in text


def test_openai_compat_has_no_http_stack_imports() -> None:
    text = (FLASHCLI_BUNDLE / "src" / "flashcli_bundle" / "openai_compat.py").read_text(
        encoding="utf-8"
    )
    assert "starlette" not in text
    assert "fastapi" not in text
    assert "uvicorn" not in text


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


# --- Phase A: re-export contract + module ownership ---

HOST_REEXPORT_FILES: dict[str, str] = {
    "models/preset_ref.py": "flashcli_bundle.preset_ref",
    "bundle/marker.py": "flashcli_bundle.marker",
    "util/download_progress.py": "flashcli_bundle.util.download_progress",
    "runtime/mirror.py": "flashcli_bundle.runtime.mirror",
    "runtime/detect.py": "flashcli_bundle.runtime.detect",
    "runtime/requirements_spec.py": "flashcli_bundle.runtime.requirements_spec",
    "models/post_pull.py": "flashcli_bundle.post_pull",
    "bundle/resolve.py": "flashcli_bundle.resolve",
}

INFER_REEXPORT_FILES: dict[str, str] = {
    "infer/runtime/detect.py": "flashcli_bundle.runtime.detect",
    "infer/runtime/requirements_spec.py": "flashcli_bundle.runtime.requirements_spec",
    "infer/runtime/mirror.py": "flashcli_bundle.runtime.mirror",
    "infer/post_pull.py": "flashcli_bundle.post_pull",
    "infer/cache.py": "flashcli_bundle.cache",
    "infer/bundle/weights.py": "flashcli_bundle.weights",
}


def _is_reexport_module(text: str, protocol_prefix: str) -> bool:
    """True when file only re-exports from protocol (no standalone business defs)."""
    import_patterns = (
        protocol_prefix,
        protocol_prefix.replace(".", " import "),
        f"from flashcli_bundle import {protocol_prefix.rsplit('.', 1)[-1]}",
    )
    if not any(p in text for p in import_patterns):
        return False
    if "from flashcli_bundle" not in text:
        return False
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return False
    return True


@pytest.mark.parametrize("rel,prefix", HOST_REEXPORT_FILES.items())
def test_host_modules_are_protocol_reexports(rel: str, prefix: str) -> None:
    path = HOST_SRC / rel
    assert path.is_file(), f"missing host module {rel}"
    text = path.read_text(encoding="utf-8")
    import_patterns = (
        prefix,
        f"from flashcli_bundle import {prefix.rsplit('.', 1)[-1]}",
    )
    assert any(p in text for p in import_patterns), f"{rel} must re-export from {prefix}"
    assert _is_reexport_module(text, prefix) or rel == "models/cache.py", (
        f"{rel} must be a thin re-export (or host wrapper for cache)"
    )


@pytest.mark.parametrize("rel,prefix", INFER_REEXPORT_FILES.items())
def test_infer_modules_are_protocol_reexports(rel: str, prefix: str) -> None:
    path = FLASHCLI_BUNDLE / "src" / "flashcli_bundle" / rel
    assert path.is_file(), f"missing infer module {rel}"
    text = path.read_text(encoding="utf-8")
    assert prefix in text, f"{rel} must re-export from {prefix}"
    assert _is_reexport_module(text, prefix), f"{rel} must be a thin re-export"


def test_infer_runtime_mirror_matches_protocol_logic() -> None:
    """Infer mirror must not retain stale USE_MIRROR-before-NO_MIRROR ordering."""
    proto = (
        FLASHCLI_BUNDLE / "src" / "flashcli_bundle" / "runtime" / "mirror.py"
    ).read_text(encoding="utf-8")
    assert 'os.environ.get("FLASHCLI_NO_MIRROR")' in proto
    assert proto.index("FLASHCLI_NO_MIRROR") < proto.index("FLASHCLI_USE_MIRROR")


def test_preset_has_engine_and_description() -> None:
    from flashcli_bundle.preset import Preset

    p = Preset(name="test", raw={"engine": "model_bundle", "description": "demo"})
    assert p.engine == "model_bundle"
    assert p.description == "demo"


def test_protocol_modules_import_without_serve_or_hf() -> None:
    import flashcli_bundle.cache
    import flashcli_bundle.post_pull
    import flashcli_bundle.resolve
    import flashcli_bundle.weights
    import flashcli_bundle.activate_core
    import flashcli_bundle.runtime.mirror

    assert flashcli_bundle.cache.ensure_model_cached is not None
    assert flashcli_bundle.resolve.load_preset_bundle is not None
    assert not hasattr(flashcli_bundle.runtime.mirror, "download_github_release_asset")


def test_host_cache_is_thin_wrapper() -> None:
    text = (HOST_SRC / "models" / "cache.py").read_text(encoding="utf-8")
    assert "flashcli_bundle.cache" in text or "flashcli_bundle import cache" in text
    assert "def preset_cache_dir" not in text
    assert "def _read_marker" not in text


# --- Module placement: host/infer-only logic must not grow in protocol ---

# Host-only modules still under flashcli_bundle/ (migration backlog — do not add).
HOST_ONLY_PROTOCOL_MODULES = frozenset()

HOST_ONLY_MIRROR_SYMBOLS = frozenset({
    "download_github_release_asset",
    "github_release_download_urls",
    "proxied_github_url",
    "DEFAULT_GIT_PROXY_PREFIX",
})

_PLACEMENT_MARKERS = (
    "Host-only",
    "Infer-only",
    "host only",
    "infer only",
    "HOST_ONLY_PROTOCOL",
)


def test_module_layers_documents_single_layer_placement_rule() -> None:
    en = (ROOT / "docs" / "module_layers.md").read_text(encoding="utf-8")
    zh = (ROOT / "docs" / "module_layers.zh-CN.md").read_text(encoding="utf-8")
    assert "Host-only" in en or "host only" in en.lower()
    assert "Infer-only" in en or "infer only" in en.lower()
    assert any(m in zh for m in _PLACEMENT_MARKERS)


def test_host_only_protocol_allowlist_documented_in_module_layers() -> None:
    if not HOST_ONLY_PROTOCOL_MODULES:
        return
    doc = (ROOT / "docs" / "module_layers.md").read_text(encoding="utf-8")
    for mod in HOST_ONLY_PROTOCOL_MODULES:
        stem = mod.rsplit(".", 1)[-1]
        assert stem in doc, f"document migration backlog for {mod} in module_layers.md"


def test_host_only_protocol_allowlist_must_not_grow() -> None:
    """New host-only modules must not appear under flashcli_bundle/ without review."""
    proto_root = FLASHCLI_BUNDLE / "src" / "flashcli_bundle"
    allow_stems = {m.rsplit(".", 1)[-1] for m in HOST_ONLY_PROTOCOL_MODULES}
    for path in proto_root.rglob("*.py"):
        if "infer" in path.parts:
            continue
        stem = path.stem
        if stem == "__init__":
            continue
        if stem in allow_stems:
            continue
        if stem.endswith("_host_only"):
            raise AssertionError(
                f"unexpected host-only marker file {path.relative_to(ROOT)}; "
                "implement under src/flashcli/ instead"
            )


def test_host_mirror_has_github_release_helpers() -> None:
    from flashcli.runtime import mirror as host_mirror

    assert hasattr(host_mirror, "download_github_release_asset")
    assert hasattr(host_mirror, "github_release_download_urls")


def test_infer_mirror_does_not_reexport_host_github_helpers() -> None:
    text = (
        FLASHCLI_BUNDLE / "src" / "flashcli_bundle" / "infer" / "runtime" / "mirror.py"
    ).read_text(encoding="utf-8")
    for sym in HOST_ONLY_MIRROR_SYMBOLS:
        assert sym not in text, f"infer/runtime/mirror must not re-export host-only {sym}"

