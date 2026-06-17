"""Bundle runtime requirements stay inference-only (no flashcli HTTP stack)."""

from __future__ import annotations

from flashcli.runtime.requirements_spec import RuntimeRequirementsSpec


def test_bundle_spec_ignores_optional_server_group() -> None:
    spec = RuntimeRequirementsSpec(
        pip_packages=["numpy"],
        optional_groups={"server": ["fastapi", "uvicorn"]},
    )
    assert spec.pip_packages_for_bundle() == ["numpy"]
    assert spec.all_packages() == ["torch", "numpy"]


def test_pip_packages_for_bundle_is_inference_only() -> None:
    spec = RuntimeRequirementsSpec(
        pip_packages=["numpy", "transformers<4.56"],
        optional_groups={"server": ["fastapi", "uvicorn"]},
    )
    assert spec.pip_packages_for_bundle() == ["numpy", "transformers<4.56"]
