"""Tests for ModelScope weight download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flashcli.models.ms_hub import modelscope_revision_attempts
from flashcli.models.pull import _download_modelscope, download_weights


def test_modelscope_revision_main_maps_to_master() -> None:
    assert modelscope_revision_attempts("main") == ["master", None]
    assert modelscope_revision_attempts(None) == [None]
    assert modelscope_revision_attempts("v1.0") == ["v1.0", None]


def test_modelscope_download_calls_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MODELSCOPE_ENDPOINT", raising=False)
    spec = {"source": "modelscope", "repo": "org/model", "revision": "master"}
    calls: list[dict] = []

    def fake_ms(**kwargs):
        calls.append(kwargs)

    with patch("flashcli.models.ms_hub._import_snapshot_download", return_value=fake_ms):
        with patch(
            "flashcli.bundle.checkpoint.has_cached_weight_files",
            side_effect=[False, True],
        ):
            _download_modelscope(spec, tmp_path / "ckpt", quiet=True)

    assert len(calls) == 1
    assert calls[0]["model_id"] == "org/model"
    assert calls[0]["revision"] == "master"
    assert calls[0]["local_dir"] == str(tmp_path / "ckpt")


def test_modelscope_main_uses_master_revision(tmp_path: Path) -> None:
    spec = {"source": "modelscope", "repo": "org/model", "revision": "main"}
    calls: list[str | None] = []

    def fake_ms(**kwargs):
        calls.append(kwargs.get("revision"))

    with patch("flashcli.models.ms_hub._import_snapshot_download", return_value=fake_ms):
        with patch(
            "flashcli.bundle.checkpoint.has_cached_weight_files",
            side_effect=[False, True],
        ):
            _download_modelscope(spec, tmp_path / "ckpt", quiet=True)

    assert calls == ["master"]


def test_modelscope_endpoint_from_spec(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MODELSCOPE_ENDPOINT", raising=False)
    spec = {
        "source": "modelscope",
        "repo": "org/model",
        "endpoint": "https://www.modelscope.cn",
    }
    calls: list[str] = []

    def fake_ms(**kwargs):
        calls.append(kwargs["model_id"])

    with patch("flashcli.models.ms_hub._import_snapshot_download", return_value=fake_ms):
        with patch(
            "flashcli.bundle.checkpoint.has_cached_weight_files",
            side_effect=[False, True],
        ):
            download_weights(spec, tmp_path / "ckpt", quiet=True)

    assert calls == ["org/model"]


def test_modelscope_ckpt_download_accepted(tmp_path: Path) -> None:
    spec = {
        "source": "modelscope",
        "repo": "cpadyun/melband-roformer",
        "revision": "main",
    }
    dest = tmp_path / "ckpt"

    def fake_ms(**kwargs):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "MelBandRoformer.ckpt").write_bytes(b"x" * 1024)
        (dest / "config_vocals_mel_band_roformer.yaml").write_text("x: 1\n")

    with patch("flashcli.models.ms_hub._import_snapshot_download", return_value=fake_ms):
        _download_modelscope(spec, dest, quiet=True)

    assert (dest / "MelBandRoformer.ckpt").is_file()
