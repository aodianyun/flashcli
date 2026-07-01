"""Tests for protocol Preset fields used in host and infer."""

from __future__ import annotations

from flashcli_bundle.preset import Preset


def test_preset_engine_defaults_to_model_bundle() -> None:
    p = Preset(name="flashcli-bundle/pi05:1.0.4", raw={"bundle": {"repo": "https://x"}})
    assert p.engine == "model_bundle"


def test_preset_description_from_repo() -> None:
    p = Preset(
        name="flashcli-bundle/pi05:1.0.4",
        raw={"bundle": {"repo": "https://flashhub.example/pi05/1.0.4"}},
    )
    assert "bundle:repo=" in p.description
