"""Conformance fixture: baseline python RunEngine that echoes its prompt."""

from __future__ import annotations

from pathlib import Path


class RunEngine:
    def load(self, checkpoint: Path, preset, **options) -> None:
        self._checkpoint = checkpoint

    def predict(self, *, prompt: str = "", images=None, **kwargs) -> dict:
        return {"echo": prompt}
