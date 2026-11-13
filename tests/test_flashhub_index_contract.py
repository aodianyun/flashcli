"""Live FlashHub index contract: catch CDN layout drift before a release.

FlashHub changes the shape of `download_url` when its uploader changes. Two
shapes are known:

    <logical path>             (older uploads, e.g. .../run.py)
    <logical path>/<name>      (newer uploads, e.g. .../__init__.py/__init__.py)

`parseIndex` collapses the duplicated leaf. This check talks to the live API and
asserts the invariants the client relies on, so a third shape fails the check
before a release ships:

- every URL is one of the two known shapes;
- the derived path ends with the file name and has no duplicated segments;
- `flashcli-bundle.json` maps to the repo root;
- runtime libraries stay directly inside a `runtime/<env>/` directory.

Run before publishing (or nightly):

    FLASHCLI_FLASHHUB_LIVE=1 pytest tests/test_flashhub_index_contract.py

It only downloads the index JSON (a few KiB per ref).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

import pytest

API = "https://flashhub-api.aodianyun.com/api/v1/repos"

# Mix of an older upload and the newer layout.
REFS = [
    "rsi-flashrt/qwen35_4b_nvfp4:1.0.1",
    "flashcli-bundle/qwen3_8b_nvfp4:1.0.0",
    "flashcli-bundle/pi05_libero:1.0.4",
]


def _cdn_relative(download_url: str) -> str:
    path = urllib.parse.urlparse(download_url).path
    marker = "/versions/"
    if marker in path:
        path = path.split(marker, 1)[1].split("/", 1)[1]
    return path.strip("/")


def _derived_path(download_url: str, file_name: str) -> str:
    """Mirror parseIndex after the duplicated-leaf fix."""
    path = _cdn_relative(download_url)
    if "/" not in path:
        return file_name
    parent = path.rsplit("/", 1)[0]
    if parent.rsplit("/", 1)[-1] == file_name:
        return parent
    return parent + "/" + file_name


def _fetch(ref: str) -> list[dict]:
    req = urllib.request.Request(f"{API}/{ref}", headers={"User-Agent": "flashcli-tests"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    return payload["data"]["files"]


@pytest.mark.skipif(
    os.environ.get("FLASHCLI_FLASHHUB_LIVE") != "1",
    reason="set FLASHCLI_FLASHHUB_LIVE=1 to check the live FlashHub index",
)
@pytest.mark.parametrize("ref", REFS)
def test_live_index_layout_is_understood(ref: str) -> None:
    files = _fetch(ref)
    assert files, f"no files for {ref}"

    derived = {}
    for f in files:
        raw = _cdn_relative(f["download_url"])
        name = f["file_name"]
        path = _derived_path(f["download_url"], name)

        # Only the two known shapes are allowed. A new shape (deeper nesting,
        # missing name, ...) must be added to parseIndex and to this test.
        assert raw in (path, f"{path}/{name}"), f"unknown CDN layout: {raw} (file_name={name}, {ref})"

        segments = path.split("/")
        assert segments[-1] == name, f"derived path {path} does not end with {name} ({ref})"
        for i in range(1, len(segments)):
            assert segments[i] != segments[i - 1], f"duplicated segment in {path} ({ref})"
        derived[path] = f

    assert "flashcli-bundle.json" in derived, f"manifest is not at the repo root for {ref}"

    for path in derived:
        if path.endswith(".so"):
            segments = path.split("/")
            assert len(segments) == 3 and segments[0] == "runtime", (
                f"runtime library outside runtime/<env>/: {path} ({ref})"
            )
