"""Minimal v4 conformance entry: reports the selected environment."""

from __future__ import annotations

import os


class RunEngine:
    def load(self, checkpoint, preset, **options):
        del checkpoint, preset, options

    def predict(self, *, prompt: str = "", **kwargs):
        del prompt, kwargs
        print(
            "V4_RUNTIME_MATRIX_OK",
            os.environ.get("FLASHCLI_RUNTIME_ENV_KEY", ""),
            flush=True,
        )
        return {"text": "ok"}
