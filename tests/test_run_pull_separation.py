"""run and pull both ensure weights on the host; bundle venv stays offline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.cli import _ensure_host_weights_before_reexec
from flashcli.models.registry import Preset


def test_run_host_weights_download_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    preset = Preset(
        name="bundles/groot_n16",
        raw={"engine": "model_bundle"},
        cache_key="groot_n16/test",
    )
    seen: dict[str, bool] = {}

    def _fake_ensure(*_args, **kwargs) -> Path:
        seen["download"] = kwargs.get("download", True)
        return Path("/tmp/checkpoint")

    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.validate_preset_before_sync",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "flashcli.runtime.reexec.prepare_bundle_runtime",
        lambda *a, **k: ("/tmp/rt", Path("/tmp/bundle")),
    )
    monkeypatch.setattr(
        "flashcli.bundle.variants.resolve_effective_model_variant",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("flashcli.models.cache.ensure_model_cached", _fake_ensure)

    _ensure_host_weights_before_reexec(
        preset,
        bundle=Path("/tmp/bundle"),
        checkpoint=None,
        mtp_checkpoint=None,
        quiet=True,
    )
    assert seen.get("download") is True


def test_pull_also_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from flashcli.cli import app

    seen: dict[str, bool] = {}

    def _fake_ensure(*_args, **kwargs) -> Path:
        seen["download"] = kwargs.get("download", True)
        return Path("/tmp/checkpoint")

    monkeypatch.setattr(
        "flashcli.bundle.preset_validate.validate_preset_before_sync",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "flashcli.runtime.reexec.prepare_bundle_runtime",
        lambda *a, **k: ("/tmp/rt", Path("/tmp/bundle")),
    )
    monkeypatch.setattr(
        "flashcli.bundle.variants.resolve_effective_model_variant",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("flashcli.cli.ensure_environment", lambda **k: None)
    monkeypatch.setattr(
        "flashcli.models.preset_ref.resolve_run_target",
        lambda ref: (
            Preset(name=ref, raw={"engine": "model_bundle"}, cache_key="x"),
            None,
        ),
    )
    monkeypatch.setattr("flashcli.models.cache.ensure_model_cached", _fake_ensure)

    runner = CliRunner()
    with patch("flashcli.cli.config.skip_auto_install", return_value=True):
        result = runner.invoke(app, ["pull", "bundles/groot_n16"], catch_exceptions=False)

    assert result.exit_code == 0
    assert seen.get("download") is True
