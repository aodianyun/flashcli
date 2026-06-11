"""Tests for bundle venv infer bootstrap launcher."""

from __future__ import annotations

from pathlib import Path

from flashcli.runtime import infer_launch


def test_host_path_site_packages_layout(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    pkg = site / "flashcli"
    launch = pkg / "runtime" / "infer_launch.py"
    launch.parent.mkdir(parents=True)
    launch.write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    infer_launch._LAUNCH = launch.resolve()
    infer_launch._PKG = infer_launch._LAUNCH.parent.parent
    assert infer_launch._host_sys_path_entry() == site.resolve()


def test_host_path_editable_layout(tmp_path: Path) -> None:
    repo = tmp_path / "flashcli"
    src = repo / "src" / "flashcli"
    launch = src / "runtime" / "infer_launch.py"
    launch.parent.mkdir(parents=True)
    launch.write_text("", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    infer_launch._LAUNCH = launch.resolve()
    infer_launch._PKG = infer_launch._LAUNCH.parent.parent
    assert infer_launch._host_sys_path_entry() == (repo / "src").resolve()


def test_main_prepends_path(monkeypatch, tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    pkg = site / "flashcli"
    launch = pkg / "runtime" / "infer_launch.py"
    launch.parent.mkdir(parents=True)
    launch.touch()
    infer_launch._LAUNCH = launch.resolve()
    infer_launch._PKG = infer_launch._LAUNCH.parent.parent

    seen: dict[str, list[str]] = {}

    def fake_run_module(name: str, **kwargs) -> None:
        seen["path"] = list(infer_launch.sys.path)
        seen["name"] = [name]

    monkeypatch.setattr(infer_launch.sys, "path", [])
    monkeypatch.setattr(infer_launch.runpy, "run_module", fake_run_module)
    infer_launch.main()
    assert seen["name"] == ["flashcli.runtime.infer"]
    assert seen["path"][0] == str(site.resolve())
