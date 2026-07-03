"""GROOT N1.7 observation layout for Gr00tPolicy aux capture."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GROOT_N17 = ROOT / "bundles" / "groot_n17"
if str(GROOT_N17) not in sys.path:
    sys.path.insert(0, str(GROOT_N17))

from _groot_n17_preprocess import (  # noqa: E402
    _default_state_row,
    parse_observation_gr00t,
)


def _oxe_droid_configs() -> dict:
    return {
        "video": SimpleNamespace(
            delta_indices=[-15, 0],
            modality_keys=["exterior_image_1_left", "wrist_image_left"],
        ),
        "state": SimpleNamespace(
            delta_indices=[0],
            modality_keys=["eef_9d", "gripper_position", "joint_position"],
        ),
        "language": SimpleNamespace(
            delta_indices=[0],
            modality_keys=["task"],
        ),
    }


def test_default_state_row_uses_identity_rot6d_for_eef_9d() -> None:
    row = _default_state_row("eef_9d", 9)
    assert row.shape == (9,)
    assert row[:3].tolist() == [0.0, 0.0, 0.0]
    assert row[3:9].tolist() == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def test_parse_observation_gr00t_single_frame_video_gets_temporal_dim() -> None:
    img = np.zeros((256, 256, 3), dtype=np.uint8)
    obs = {
        "video.exterior_image_1_left": img,
        "video.wrist_image_left": img,
        "state.eef_9d": np.zeros((1, 9), dtype=np.float32),
        "state.gripper_position": np.zeros((1, 1), dtype=np.float32),
        "state.joint_position": np.zeros((1, 7), dtype=np.float32),
        "task": "pick up the block",
    }
    parsed = parse_observation_gr00t(obs, _oxe_droid_configs())
    left = parsed["video"]["exterior_image_1_left"]
    assert left.shape == (1, 2, 256, 256, 3)
    assert parsed["state"]["eef_9d"].shape == (1, 1, 9)


def test_parse_observation_gr00t_accepts_flashrt_state_layout() -> None:
    img = np.zeros((2, 128, 128, 3), dtype=np.uint8)
    obs = {
        "video.exterior_image_1_left": img,
        "video.wrist_image_left": img,
        "state.eef_9d": np.zeros((1, 1, 9), dtype=np.float32),
        "state.gripper_position": np.zeros((1, 1, 1), dtype=np.float32),
        "state.joint_position": np.zeros((1, 1, 7), dtype=np.float32),
        "task": "move",
    }
    parsed = parse_observation_gr00t(obs, _oxe_droid_configs())
    assert parsed["state"]["eef_9d"].shape == (1, 1, 9)
    assert parsed["state"]["gripper_position"].shape == (1, 1, 1)
