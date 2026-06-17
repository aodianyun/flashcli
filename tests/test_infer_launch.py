"""Tests for bundle venv infer bootstrap launcher."""

from __future__ import annotations

from pathlib import Path

from flashcli.runtime import infer_launch


def test_main_uses_host_import_shim_not_site_packages(monkeypatch, tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    pkg = site / "flashcli"
    launch = pkg / "runtime" / "infer_launch.py"
    launch.parent.mkdir(parents=True)
    launch.touch()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (site / "huggingface_hub").mkdir()

    home = tmp_path / "home"
    import flashcli.runtime.flashcli_shared as shared

    monkeypatch.setattr(shared.config, "FLASHCLI_HOME", home)
    monkeypatch.setattr(shared, "installed_flashcli_package_root", lambda: pkg.resolve())
    monkeypatch.setattr(shared, "editable_flashcli_src", lambda: None)

    seen: dict[str, list[str]] = {}

    def fake_run_module(name: str, **kwargs) -> None:
        seen["path"] = list(infer_launch.sys.path)
        seen["name"] = [name]

    monkeypatch.setattr(infer_launch, "_ensure_bundle_protocol_package", lambda: None)
    monkeypatch.setattr(infer_launch.sys, "path", [])
    monkeypatch.setattr(infer_launch.runpy, "run_module", fake_run_module)
    infer_launch.main()

    shim = (home / "host-import").resolve()
    assert seen["name"] == ["flashcli.runtime.infer"]
    assert seen["path"][0] == str(shim)
    assert seen["path"][0] != str(site.resolve())
