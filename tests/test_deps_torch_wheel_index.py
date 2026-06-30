"""Torch CUDA wheel index routing for bundle venv installs."""

from __future__ import annotations

from flashcli_bundle.infer.deps import (
    pypi_prereqs_for_isolated_install,
    resolve_torch_index_specs,
    torch_ecosystem_nodeps_needed,
)
from flashcli_bundle.runtime.mirror import resolve_torch_index_url
from flashcli_bundle.runtime.requirements_spec import (
    RuntimeRequirementsSpec,
    uses_torch_cuda_wheel_index,
)


def test_uses_torch_cuda_wheel_index() -> None:
    assert uses_torch_cuda_wheel_index("torchaudio>=2.4")
    assert uses_torch_cuda_wheel_index("torchvision")
    assert uses_torch_cuda_wheel_index("torchtext==2.4.0")
    assert not uses_torch_cuda_wheel_index("transformers>=4.57")
    assert not uses_torch_cuda_wheel_index("omnivoice")


def test_torch_ecosystem_nodeps_when_stack_covered() -> None:
    covered = frozenset({"torch", "torchaudio"})
    assert torch_ecosystem_nodeps_needed(["torchaudio>=2.0"], covered)
    assert not torch_ecosystem_nodeps_needed(["numpy>=1.0"], covered)
    assert not torch_ecosystem_nodeps_needed(
        ["torchaudio>=2.0"],
        frozenset({"torch"}),
    )


def test_resolve_torch_index_specs_infers_from_pypi_wheel_metadata() -> None:
    spec = RuntimeRequirementsSpec(
        torch_package="torch",
        pip_packages=["omnivoice"],
    )
    wheel_cache = {"omnivoice": ["torchaudio>=2.0", "numpy>=1.0"]}
    specs, covered = resolve_torch_index_specs(spec, wheel_cache)
    assert specs == ["torch", "torchaudio"]
    assert covered == frozenset({"torch", "torchaudio"})


def test_resolve_torch_index_specs_keeps_manifest_pins() -> None:
    spec = RuntimeRequirementsSpec(
        torch_package="torch",
        pip_packages=["torchaudio>=2.4", "omnivoice"],
    )
    wheel_cache = {"omnivoice": ["torchaudio>=2.0"]}
    specs, covered = resolve_torch_index_specs(spec, wheel_cache)
    assert specs[0] == "torch"
    assert "torchaudio>=2.4" in specs
    assert covered == frozenset({"torch", "torchaudio"})


def test_resolve_torch_index_url_cu128() -> None:
    url = resolve_torch_index_url("cu128")
    assert "cu128" in url


def test_pypi_prereqs_for_isolated_install_skips_torch_and_eval_extras() -> None:
    requires = [
        "torch>=2.4",
        "torchaudio>=2.4",
        "transformers>=5.3.0",
        "numpy",
        "jiwer==3.1.0; extra == 'eval'",
    ]
    prereqs = pypi_prereqs_for_isolated_install(requires)
    assert "transformers>=5.3.0" in prereqs
    assert "numpy" in prereqs
    assert not any("torch" in p for p in prereqs)
    assert not any("jiwer" in p for p in prereqs)


def test_format_torch_ecosystem_constraint_lines_pins_local_versions() -> None:
    from flashcli_bundle.infer.deps import format_torch_ecosystem_constraint_lines

    lines = format_torch_ecosystem_constraint_lines(
        {
            "torchaudio": "2.6.0+cu128",
            "torch": "2.6.0+cu128",
        }
    )
    assert lines == [
        "torch==2.6.0+cu128",
        "torchaudio==2.6.0+cu128",
    ]
