"""Tests for Hugging Face Hub CLI download helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from flashcli.models.hf_hub import (
    HF_MIRROR_ENDPOINT,
    HF_OFFICIAL_ENDPOINT,
    _hf_cli_command,
    apply_hub_timeouts,
    download_endpoint_order,
    filter_download_endpoints,
    hub_cli_on_path,
    hub_endpoint_env,
    run_hf_cli_download,
)


def test_download_endpoint_order_default_official_first() -> None:
    assert download_endpoint_order("", explicit=False) == ["", HF_MIRROR_ENDPOINT]


def test_download_endpoint_order_explicit_mirror_only() -> None:
    assert download_endpoint_order(HF_MIRROR_ENDPOINT, explicit=True) == [
        HF_MIRROR_ENDPOINT
    ]


def test_hub_endpoint_env_sets_hf_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    with hub_endpoint_env(HF_MIRROR_ENDPOINT):
        assert os.environ["HF_ENDPOINT"] == HF_MIRROR_ENDPOINT
    assert "HF_ENDPOINT" not in os.environ


def test_hf_cli_command_prefers_hf(tmp_path: Path) -> None:
    with patch("flashcli.models.hf_hub.shutil.which", return_value="/usr/bin/hf"):
        cmd = _hf_cli_command("org/model", tmp_path, revision="main", allow_patterns=None)
    assert cmd[:4] == ["/usr/bin/hf", "download", "org/model", "--local-dir"]
    assert "--revision" in cmd and "main" in cmd


def test_apply_hub_timeouts_defaults(monkeypatch) -> None:
    monkeypatch.delenv("HF_HUB_ETAG_TIMEOUT", raising=False)
    monkeypatch.delenv("HF_HUB_DOWNLOAD_TIMEOUT", raising=False)
    monkeypatch.delenv("FLASHCLI_HF_ETAG_TIMEOUT", raising=False)
    env = apply_hub_timeouts({})
    assert env["HF_HUB_ETAG_TIMEOUT"] == "5"
    assert env["HF_HUB_DOWNLOAD_TIMEOUT"] == "5"


def test_apply_hub_timeouts_respects_existing(monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_ETAG_TIMEOUT", "30")
    env = apply_hub_timeouts({})
    assert env["HF_HUB_ETAG_TIMEOUT"] == "30"


def test_filter_download_endpoints_skips_unreachable_official(monkeypatch) -> None:
    monkeypatch.delenv("FLASHCLI_SKIP_HF_PROBE", raising=False)
    with patch("flashcli.models.hf_hub.hub_reachable", return_value=False):
        out = filter_download_endpoints(
            ["", HF_MIRROR_ENDPOINT], repo="org/model", revision="main", quiet=True
        )
    assert out == [HF_MIRROR_ENDPOINT]


def test_run_hf_cli_download_quiet_captures_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    with patch("flashcli.models.hf_hub.shutil.which", return_value="/usr/bin/hf"):
        with patch("flashcli.models.hf_hub.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            run_hf_cli_download(
                "org/model",
                tmp_path / "ckpt",
                revision="main",
                endpoint=HF_MIRROR_ENDPOINT,
                quiet=True,
            )
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs.get("capture_output") is True
    env = mock_run.call_args.kwargs["env"]
    assert env["HF_ENDPOINT"] == HF_MIRROR_ENDPOINT


def test_run_hf_cli_download_streams_when_not_quiet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setenv("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    with patch("flashcli.models.hf_hub.shutil.which", return_value="/usr/bin/hf"):
        with patch("flashcli.models.hf_hub.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            run_hf_cli_download(
                "org/model",
                tmp_path / "ckpt",
                endpoint=HF_MIRROR_ENDPOINT,
                quiet=False,
            )
    assert mock_run.call_args.kwargs.get("capture_output") is not True
    env = mock_run.call_args.kwargs["env"]
    assert "HF_HUB_DISABLE_PROGRESS_BARS" not in env
    assert env.get("HF_HUB_VERBOSITY") == "error"


def test_hf_cli_command_falls_back_to_python_module(tmp_path: Path) -> None:
    with patch("flashcli.models.hf_hub.hub_cli_on_path", return_value=None):
        cmd = _hf_cli_command("org/m", tmp_path, revision="main", allow_patterns=None)
    assert "huggingface_hub.cli.hf" in cmd
    assert cmd[0] == sys.executable


def test_run_hf_cli_download_uses_python_module_when_no_hf_on_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    with patch("flashcli.models.hf_hub.hub_cli_on_path", return_value=None):
        with patch("flashcli.models.hf_hub.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            run_hf_cli_download(
                "org/model",
                tmp_path / "ckpt",
                endpoint=HF_MIRROR_ENDPOINT,
                quiet=True,
            )
    assert mock_run.call_args.args[0][1:3] == ["-m", "huggingface_hub.cli.hf"]
