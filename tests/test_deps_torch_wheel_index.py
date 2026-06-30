"""Torch CUDA wheel index routing for bundle venv installs."""

from __future__ import annotations

from flashcli_bundle.runtime.mirror import resolve_torch_index_url
from flashcli_bundle.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    pip_nodeps_names,
    uses_torch_cuda_wheel_index,
)


def test_uses_torch_cuda_wheel_index() -> None:
    assert uses_torch_cuda_wheel_index("torchaudio>=2.4")
    assert uses_torch_cuda_wheel_index("torchvision")
    assert uses_torch_cuda_wheel_index("torchtext==2.4.0")
    assert not uses_torch_cuda_wheel_index("transformers>=4.57")
    assert not uses_torch_cuda_wheel_index("omnivoice")


def test_pip_nodeps_names_defaults_omnivoice() -> None:
    spec = RuntimeRequirementsSpec(pip_packages=["numpy", "omnivoice"])
    assert "omnivoice" in pip_nodeps_names(spec)
    assert "numpy" not in pip_nodeps_names(spec)


def test_pip_nodeps_names_from_manifest() -> None:
    spec = RuntimeRequirementsSpec(
        pip_packages=["foo", "bar"],
        pip_nodeps=["SomePkg>=1.0", "bar"],
    )
    names = pip_nodeps_names(spec)
    assert "omnivoice" in names
    assert "somepkg" in names
    assert "bar" in names
    assert "foo" not in names


def test_resolve_torch_index_url_cu128() -> None:
    url = resolve_torch_index_url("cu128")
    assert "cu128" in url


def test_torch_cuda_stack_probe_missing_torchaudio_is_not_ok() -> None:
    from flashcli_bundle.infer.deps import _TORCH_CUDA_STACK_PROBE

    assert "ImportError" in _TORCH_CUDA_STACK_PROBE
    assert "SystemExit(1)" in _TORCH_CUDA_STACK_PROBE
    assert "SystemExit(0)" not in _TORCH_CUDA_STACK_PROBE.split("except ImportError:")[1].split("except RuntimeError")[0]
