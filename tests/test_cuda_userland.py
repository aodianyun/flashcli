"""CUDA userland SONAME mapping and LD_LIBRARY_PATH helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flashcli_bundle.cuda_userland import (
    cuda_pip_packages_for_tag,
    cuda_sonames_for_tag,
    find_soname_file,
    nvidia_lib_dirs,
    prepend_ld_library_path,
)


@pytest.mark.parametrize(
    ("tag", "want_cublas"),
    [
        ("124", "libcublas.so.12"),
        ("128", "libcublas.so.12"),
        ("130", "libcublas.so.13"),
    ],
)
def test_cuda_sonames_for_tag(tag: str, want_cublas: str) -> None:
    names = cuda_sonames_for_tag(tag)
    assert want_cublas in names
    assert any(n.startswith("libcudart.so.") for n in names)


def test_cuda_pip_packages_cu13() -> None:
    pkgs = cuda_pip_packages_for_tag("130")
    assert any("cublas" in p for p in pkgs)
    assert any("runtime" in p for p in pkgs)
    assert all("<14" in p for p in pkgs)


def test_prepend_ld_library_path_prepends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("LD_LIBRARY_PATH", "/already")
    added = prepend_ld_library_path([a, b])
    assert a in added and b in added
    parts = os.environ["LD_LIBRARY_PATH"].split(":")
    assert str(a.resolve()) in parts
    assert str(b.resolve()) in parts
    assert parts.index(str(a.resolve())) < parts.index("/already")


def test_prepend_ld_library_path_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "lib"
    d.mkdir()
    monkeypatch.setenv("LD_LIBRARY_PATH", str(d.resolve()))
    assert prepend_ld_library_path([d]) == []


def test_nvidia_lib_dirs_prefers_cu13_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "site-packages"
    cu13 = purelib / "nvidia" / "cu13" / "lib"
    legacy = purelib / "nvidia" / "cublas" / "lib"
    cu13.mkdir(parents=True)
    legacy.mkdir(parents=True)
    monkeypatch.setattr(
        "flashcli_bundle.cuda_userland.venv_purelib",
        lambda _python: purelib,
    )
    dirs = nvidia_lib_dirs(tmp_path / "python")
    assert dirs[0] == cu13.resolve()
    assert legacy.resolve() in dirs


def test_find_soname_file_cu13_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    purelib = tmp_path / "site-packages"
    lib = purelib / "nvidia" / "cu13" / "lib"
    lib.mkdir(parents=True)
    so = lib / "libcublas.so.13"
    so.write_bytes(b"")
    monkeypatch.setattr(
        "flashcli_bundle.cuda_userland.venv_purelib",
        lambda _python: purelib,
    )
    found = find_soname_file(tmp_path / "python", "libcublas.so.13")
    assert found == so.resolve()
