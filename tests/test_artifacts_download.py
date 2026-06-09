"""Tests for FlashHub repo download path filtering."""

from __future__ import annotations

from flashcli.bundle.artifacts import _should_download_repo_file


def test_skip_other_runtime_dirs() -> None:
    runtime_map = {
        "sm89-cu124-linux-x86_64-py312": "runtime/sm89-cu124-linux-x86_64-py312",
        "sm89-cu130-linux-x86_64-py312": "runtime/sm89-cu130-linux-x86_64-py312",
    }
    selected = "runtime/sm89-cu124-linux-x86_64-py312"
    assert _should_download_repo_file("run.py", runtime_map=runtime_map, selected_artifact_rel=selected)
    assert _should_download_repo_file(
        "runtime/sm89-cu124-linux-x86_64-py312/flash_rt_kernels-sm89-cu124-linux-x86_64-py312.so",
        runtime_map=runtime_map,
        selected_artifact_rel=selected,
    )
    assert not _should_download_repo_file(
        "runtime/sm89-cu130-linux-x86_64-py312/flash_rt_kernels-sm89-cu130-linux-x86_64-py312.so",
        runtime_map=runtime_map,
        selected_artifact_rel=selected,
    )
