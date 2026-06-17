"""Serve package must not require FastAPI until build_app is used."""

from __future__ import annotations

import importlib
import sys


def test_openai_bridge_import_without_fastapi(monkeypatch) -> None:
    real_import = importlib.import_module

    def fake_import(name, package=None):
        if name == "fastapi" or name.startswith("fastapi."):
            raise ImportError("fastapi intentionally blocked for test")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    sys.modules.pop("flashcli_bundle.infer.serve.openai_bridge", None)
    sys.modules.pop("flashcli_bundle.infer.serve", None)

    mod = importlib.import_module("flashcli_bundle.infer.serve.openai_bridge")
    assert callable(mod.sse_lines_to_chat_chunks)
