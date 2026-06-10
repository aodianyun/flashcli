"""Tests for python-build-standalone release parsing."""

from __future__ import annotations

from flashcli.standalone_release import (
    assets_from_release,
    asset_from_manifest,
    filter_assets,
    parse_py_minors_csv,
    py_minor_tag,
)


def _sample_payload() -> dict:
    tag = "20260602"
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": f"cpython-3.12.10+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": f"https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/cpython-3.12.10+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "size": 15000000,
            },
            {
                "name": f"cpython-3.11.12+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": f"https://example.test/3.11.tar.gz",
                "size": 14000000,
            },
            {
                "name": f"cpython-3.15.0b2+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": f"https://example.test/3.15b2.tar.gz",
                "size": 13000000,
            },
            {
                "name": f"cpython-3.12.10+{tag}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
                "browser_download_url": "https://example.test/stripped.tar.gz",
                "size": 1,
            },
        ],
    }


def test_py_minor_tag() -> None:
    assert py_minor_tag(3, 12) == "312"


def test_parse_py_minors_all() -> None:
    assert parse_py_minors_csv("all") is None
    assert parse_py_minors_csv("310,312") == ["310", "312"]


def test_assets_from_release() -> None:
    assets = assets_from_release(_sample_payload())
    names = {a.filename for a in assets}
    assert "cpython-3.12.10+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz" in names
    assert "cpython-3.11.12+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz" in names
    assert all(not n.endswith("_stripped.tar.gz") for n in names)


def test_filter_assets_stable_only() -> None:
    assets = filter_assets(
        assets_from_release(_sample_payload()),
        triplets={"x86_64-unknown-linux-gnu"},
        py_minors=None,
        include_pre_release=False,
    )
    assert len(assets) == 2
    assert all(a.py_minor in ("311", "312") for a in assets)


def test_filter_assets_include_pre_release() -> None:
    assets = filter_assets(
        assets_from_release(_sample_payload()),
        triplets={"x86_64-unknown-linux-gnu"},
        py_minors=None,
        include_pre_release=True,
    )
    assert any(a.py_minor == "315" for a in assets)


def test_asset_from_manifest() -> None:
    manifest = {
        "standalone_tag": "20260602",
        "files": [
            {
                "py_minor": "312",
                "triplet": "x86_64-unknown-linux-gnu",
                "filename": "cpython-3.12.10+20260602-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "url": "https://cdn.example/312.tar.gz",
                "md5": "abc",
            }
        ],
    }
    asset = asset_from_manifest(manifest, "312", "x86_64-unknown-linux-gnu")
    assert asset is not None
    assert asset.url == "https://cdn.example/312.tar.gz"
    assert asset.md5 == "abc"
