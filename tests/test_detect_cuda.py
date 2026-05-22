"""CUDA tag detection from driver (nvidia-smi)."""

from __future__ import annotations

from unittest.mock import patch

from flashcli.runtime.detect import detect_cuda_tag_from_nvidia_smi


def test_detect_cuda_tag_from_nvidia_smi_cuda_13() -> None:
    banner = "CUDA Version: 13.0"
    with patch("flashcli.runtime.detect.shutil.which", return_value="/usr/bin/nvidia-smi"):
        with patch(
            "flashcli.runtime.detect.subprocess.run",
            return_value=type("R", (), {"stdout": banner})(),
        ):
            assert detect_cuda_tag_from_nvidia_smi() == "130"


def test_detect_cuda_tag_from_nvidia_smi_cuda_12_4() -> None:
    banner = "CUDA Version: 12.4"
    with patch("flashcli.runtime.detect.shutil.which", return_value="/usr/bin/nvidia-smi"):
        with patch(
            "flashcli.runtime.detect.subprocess.run",
            return_value=type("R", (), {"stdout": banner})(),
        ):
            assert detect_cuda_tag_from_nvidia_smi() == "124"
