"""Tests for HTTP download progress helpers."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from flashcli.util.download_progress import download_url_to_path


def test_download_url_to_path_writes_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.bin"
    data = b"hello-flashcli"

    class Resp:
        headers = {"Content-Length": str(len(data))}

        def __init__(self) -> None:
            self._buf = io.BytesIO(data)

        def read(self, n: int = -1) -> bytes:
            return self._buf.read(n if n <= 0 else n)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("flashcli_bundle.util.download_progress.urlopen", lambda *_a, **_k: Resp()):
        nbytes = download_url_to_path("https://example/file", dest, quiet=True)

    assert dest.read_bytes() == data
    assert nbytes == len(data)
