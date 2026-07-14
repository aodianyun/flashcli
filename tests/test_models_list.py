"""Tests for ``flashcli models list`` weight status."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from flashcli.bundle.marker import write_preset_marker
from flashcli.cli import app
from flashcli.models.registry import Preset
from flashcli_bundle import paths as config


@pytest.fixture
def flashcli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "flashcli-home"
    monkeypatch.setenv("FLASHCLI_HOME", str(home))
    config.FLASHCLI_HOME = home
    config.BUNDLES_DIR = home / "bundles"
    config.MODELS_DIR = home / "models"
    config.RUNTIMES_DIR = home / "runtimes"
    config.CACHE_DIR = home / "cache" / "downloads"
    return home


def test_models_list_local_ref_reports_weights_cached(flashcli_home: Path) -> None:
    cache_key = "higgs_audio-local-40da4a4ec462/local"
    preset = Preset(
        name="local:higgs_audio-local-40da4a4ec462",
        raw={"bundle": {"local_root": "/app/flashcli/bundles/higgs_audio/dist"}},
        cache_key=cache_key,
    )
    write_preset_marker(
        preset,
        {
            "source": "local",
            "local_root": "/app/flashcli/bundles/higgs_audio/dist",
            "runtime_id": "higgs_audio-local-40da4a4ec462",
            "bundle_root": "/app/flashcli/bundles/higgs_audio/dist",
            "env_key": "sm120-cu130-linux-x86_64-py310",
        },
    )
    weights = config.MODELS_DIR / cache_key / "checkpoint"
    weights.mkdir(parents=True)
    (weights / "model.safetensors").write_bytes(b"x")

    result = CliRunner().invoke(app, ["models", "list"])
    assert result.exit_code == 0, result.output
    assert "local:higgs_audio-local-40da4a4ec462" in result.output
    assert "weights:cached" in result.output
    assert "weights:missing" not in result.output
