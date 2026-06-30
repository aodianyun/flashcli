"""Torch CUDA wheel index routing for bundle venv installs."""

from __future__ import annotations

from flashcli_bundle.infer.deps import torch_ecosystem_nodeps_needed
from flashcli_bundle.runtime.mirror import resolve_torch_index_url
from flashcli_bundle.runtime.requirements_spec import (
    declared_package_names,
    uses_torch_cuda_wheel_index,
)
from flashcli_bundle.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
)


def test_uses_torch_cuda_wheel_index() -> None:
    assert uses_torch_cuda_wheel_index("torchaudio>=2.4")
    assert uses_torch_cuda_wheel_index("torchvision")
    assert uses_torch_cuda_wheel_index("torchtext==2.4.0")
    assert not uses_torch_cuda_wheel_index("transformers>=4.57")
    assert not uses_torch_cuda_wheel_index("omnivoice")


def test_torch_ecosystem_nodeps_needed_when_manifest_covers_wheel() -> None:
    spec = RuntimeRequirementsSpec(
        torch_package="torch",
        pip_packages=["torchaudio", "omnivoice"],
    )
    declared = declared_package_names(spec)
    assert torch_ecosystem_nodeps_needed(["torchaudio>=2.0"], declared)
    assert not torch_ecosystem_nodeps_needed(["numpy>=1.0"], declared)
    assert not torch_ecosystem_nodeps_needed(
        ["torchaudio>=2.0"],
        frozenset({"torch"}),
    )


def test_resolve_torch_index_url_cu128() -> None:
    url = resolve_torch_index_url("cu128")
    assert "cu128" in url
