"""Tests for bundle zip download cache validation."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

from flashcli.bundle.zip import _download_zip, _is_valid_zip_file


def test_is_valid_zip_file_rejects_partial(tmp_path: Path) -> None:
    bad = tmp_path / "archive.zip"
    bad.write_bytes(b"not a zip")
    assert not _is_valid_zip_file(bad)


def test_is_valid_zip_file_accepts_minimal_zip(tmp_path: Path) -> None:
    good = tmp_path / "archive.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("hello.txt", "ok")
    assert _is_valid_zip_file(good)


def test_download_zip_redownloads_corrupt_cache(tmp_path: Path) -> None:
    dest = tmp_path / "archive.zip"
    dest.write_bytes(b"partial download from ctrl-c")

    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("a.txt", "1")

    data = payload.read_bytes()

    def fake_urlopen(_req, timeout=600):
        class Resp:
            def __init__(self) -> None:
                self._buf = io.BytesIO(data)

            def read(self, n: int = -1) -> bytes:
                return self._buf.read(n if n > 0 else -1)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    with patch("flashcli.bundle.zip.urllib.request.urlopen", fake_urlopen):
        _download_zip("https://cdn.example/bundle.zip", dest, quiet=True)

    assert _is_valid_zip_file(dest)
