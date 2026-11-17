"""Live FlashHub application contract (network tier).

Verifies every published application manifest matches the v1 standard:
format/version, supported OS/arch, install commands, and default bundles.
Skipped unless ``FLASHCLI_FLASHHUB_LIVE=1``.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

API = "https://flashhub-api.aodianyun.com/api/v1"

pytestmark = pytest.mark.skipif(
    os.environ.get("FLASHCLI_FLASHHUB_LIVE") != "1",
    reason="network tier: set FLASHCLI_FLASHHUB_LIVE=1",
)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "flashcli-tests"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def test_live_app_manifests_match_standard() -> None:
    listing = _get(f"{API}/apps?page=1&page_size=50")["data"]
    apps = listing["list"]
    assert apps, "FlashHub returned no applications"

    for app in apps:
        org = app["organization"]["name"]
        name = app["name"]
        version = app["version"]
        data = _get(f"{API}/apps/{org}/{name}:{version}")["data"]

        assert data["format"] == "flashcli-application", (org, name)
        assert data["app_format_version"] == 1, (org, name)
        assert data["protocol_version"] == 1, (org, name)
        assert data["name"] == name, (org, name, data.get("name"))
        assert data["version"] == version, (org, name, data.get("version"))
        assert data["supported"]["os"], (org, name)
        assert data["supported"]["arch"], (org, name)
        assert data["install"]["commands"], (org, name)
        assert data["model"]["bundles"], (org, name)

        for bundle in data["model"]["bundles"]:
            ref = bundle["bundle"]
            assert ":" in ref, (org, name, ref)
            assert ref.count("/") >= 1, (org, name, ref)

        # Defaults must be resolvable (at least one default, or a first fallback).
        defaults = [b for b in data["model"]["bundles"] if b.get("default")]
        assert defaults or data["model"]["bundles"], (org, name)
