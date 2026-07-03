"""GROOT N1.7 vendored gr00t/ layout checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROOT_N17_ROOT = ROOT / "bundles" / "groot_n17"
VENDOR_ROOT = GROOT_N17_ROOT / "gr00t"
VENDOR_META = VENDOR_ROOT / "VENDOR.json"
VERIFY_SCRIPT = GROOT_N17_ROOT / "_verify_gr00t_vendor.py"

_HAS_VENDOR_TREE = VENDOR_META.is_file()


def test_groot_n17_manifest_has_no_gr00t_pip() -> None:
    from flashcli_bundle.manifest import load_bundle_manifest

    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    pip = manifest.raw.get("python_dependencies", {}).get("pip", [])
    joined = " ".join(str(p) for p in pip)
    assert "gr00t @ git+" not in joined


def test_groot_n17_manifest_includes_vendored_gr00t_runtime_deps() -> None:
    from flashcli_bundle.manifest import load_bundle_manifest

    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    pip = manifest.raw.get("python_dependencies", {}).get("pip", [])
    joined = " ".join(str(p) for p in pip)
    lock = (GROOT_N17_ROOT / "gr00t-inference-requirements.txt").read_text(encoding="utf-8")
    for raw in lock.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split("[")[0].strip()
        assert name in joined, f"manifest pip missing vendored gr00t runtime dep: {name}"


def test_groot_n17_manifest_pins_torch_stack() -> None:
    from flashcli_bundle.manifest import load_bundle_manifest

    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    torch_pkg = manifest.raw.get("python_dependencies", {}).get("torch", {})
    assert torch_pkg.get("package") == "torch==2.7.1"
    pip = manifest.raw.get("python_dependencies", {}).get("pip", [])
    joined = " ".join(str(p) for p in pip)
    assert "torchvision==0.22.1" in joined
    assert "transformers==4.57.3" in joined


def test_groot_n17_release_matrix_pack_files_include_gr00t() -> None:
    lines = (GROOT_N17_ROOT / "release-matrix.env").read_text(encoding="utf-8").splitlines()
    pack_line = next(line for line in lines if line.startswith("RELEASE_PACK_FILES="))
    assert "gr00t" in pack_line
    assert "backbone" not in pack_line


def test_groot_n17_validate_bundle_layout_requires_vendor() -> None:
    from flashcli_bundle.manifest import load_bundle_manifest
    from flashcli_bundle.manifest_ext import validate_bundle_layout

    manifest = load_bundle_manifest(GROOT_N17_ROOT)
    errors = validate_bundle_layout(manifest)
    if _HAS_VENDOR_TREE:
        assert not any("vendored gr00t" in e for e in errors)
    else:
        assert any("vendored gr00t" in e for e in errors)


def test_groot_n17_vendor_meta_schema() -> None:
    if not _HAS_VENDOR_TREE:
        return
    meta = json.loads(VENDOR_META.read_text(encoding="utf-8"))
    assert meta.get("package") == "gr00t"
    assert meta.get("source") == "isaac-gr00t-vendor"
    assert meta.get("git_ref")
    assert meta.get("commit")


def test_groot_n17_vendor_required_paths() -> None:
    if not _HAS_VENDOR_TREE:
        return
    required = [
        VENDOR_ROOT / "policy" / "gr00t_policy.py",
        VENDOR_ROOT / "model" / "gr00t_n1d7",
        VENDOR_ROOT / "data" / "embodiment_tags.py",
        VENDOR_ROOT / "eval" / "open_loop_eval.py",
    ]
    missing = [str(p.relative_to(GROOT_N17_ROOT)) for p in required if not p.exists()]
    assert not missing, f"missing vendored paths: {missing}"


def test_groot_n17_vendor_verify_script() -> None:
    if not _HAS_VENDOR_TREE:
        return
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(GROOT_N17_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_groot_n17_bundle_build_includes_fa2_hdim_64_for_vlm_backbone() -> None:
    build_sh = (GROOT_N17_ROOT / "_bundle_build.sh").read_text(encoding="utf-8")
    assert 'FA2_HDIMS="64;96;128"' in build_sh
