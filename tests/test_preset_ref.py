"""Tests for FlashHub preset ref parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from flashcli.models.preset_ref import cache_key, parse_preset_ref, resolve_preset


def test_parse_short_ref() -> None:
    parsed = parse_preset_ref("flashcli-bundle/pi05_libero:1.0.3")
    assert parsed.ref == "flashcli-bundle/pi05_libero:1.0.3"
    assert parsed.variant is None
    assert parsed.repo_url.endswith("/flashcli-bundle/pi05_libero:1.0.3")
    assert parsed.cache_key == "pi05_libero/1.0.3"


def test_parse_ref_with_variant() -> None:
    parsed = parse_preset_ref("flashcli-bundle/qwen_nvfp4:1.0.1@qwen36")
    assert parsed.ref == "flashcli-bundle/qwen_nvfp4:1.0.1@qwen36"
    assert parsed.variant == "qwen36"
    assert parsed.repo_url.endswith("/flashcli-bundle/qwen_nvfp4:1.0.1")
    assert parsed.cache_key == "qwen_nvfp4/1.0.1@qwen36"


def test_parse_full_url_ref() -> None:
    url = "https://flashhub-api.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero:1.0.3"
    parsed = parse_preset_ref(url)
    assert parsed.repo_url == url
    assert parsed.ref == url


def test_parse_full_url_with_variant() -> None:
    url = "https://flashhub-api.example/api/v1/repos/flashcli-bundle/qwen_nvfp4:1.0.1"
    parsed = parse_preset_ref(f"{url}@qwen3")
    assert parsed.repo_url == url
    assert parsed.variant == "qwen3"
    assert parsed.ref == f"{url}@qwen3"
    assert parsed.cache_key == "qwen_nvfp4/1.0.1@qwen3"


def test_custom_flashhub_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    import flashcli_bundle.paths as paths

    monkeypatch.setattr(
        paths,
        "FLASHHUB_API_BASE",
        "https://staging.example/api/v1/repos",
    )
    parsed = parse_preset_ref("flashcli-bundle/pi05_libero:1.0.3")
    assert parsed.repo_url == (
        "https://staging.example/api/v1/repos/flashcli-bundle/pi05_libero:1.0.3"
    )


def test_invalid_ref_raises() -> None:
    with pytest.raises(ValueError, match="Invalid preset ref"):
        parse_preset_ref("pi05_libero")


def test_resolve_preset_builds_raw() -> None:
    preset = resolve_preset("flashcli-bundle/qwen_nvfp4:1.0.1@qwen3")
    assert preset.name == "flashcli-bundle/qwen_nvfp4:1.0.1@qwen3"
    assert preset.bundle_variant == "qwen3"
    assert preset.raw["bundle"]["repo"].endswith("/flashcli-bundle/qwen_nvfp4:1.0.1")
    assert preset.cache_key == "qwen_nvfp4/1.0.1@qwen3"


def test_cache_key_local_dev() -> None:
    assert cache_key("local:qwen_nvfp4@qwen36") == "qwen_nvfp4/local@qwen36"


def test_is_flashhub_ref() -> None:
    from flashcli.models.preset_ref import is_flashhub_ref

    assert is_flashhub_ref("flashcli-bundle/qwen_nvfp4:1.0.1@qwen36")
    assert not is_flashhub_ref("bundles/qwen_nvfp4@qwen36")


def test_parse_bundle_path_arg() -> None:
    from flashcli.models.preset_ref import parse_bundle_path_arg

    assert parse_bundle_path_arg("bundles/qwen_nvfp4@qwen36") == (
        "bundles/qwen_nvfp4",
        "qwen36",
    )
    assert parse_bundle_path_arg("bundles/qwen_nvfp4") == ("bundles/qwen_nvfp4", None)


def test_resolve_bundle_root_dotdot_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flashcli.models.preset_ref import resolve_bundle_root, resolve_run_target

    bundle_root = tmp_path / "runtimes" / "pi05_libero-abc" / "root"
    bundle_root.mkdir(parents=True)
    (bundle_root / "flashcli-bundle.json").write_text("{}", encoding="utf-8")

    work = tmp_path / "app"
    work.mkdir()
    monkeypatch.chdir(work)

    rel = "../runtimes/pi05_libero-abc/root"
    assert resolve_bundle_root(Path(rel)) == bundle_root.resolve()

    preset, path = resolve_run_target(f"{rel}/")
    assert path == bundle_root.resolve()
    assert preset.raw["bundle"]["local_root"] == str(bundle_root.resolve())
