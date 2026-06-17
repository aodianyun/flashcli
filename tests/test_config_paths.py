"""Tests for FlashHub API config."""

from __future__ import annotations

from flashcli import config


def test_flashhub_api_base_default() -> None:
    assert config.FLASHHUB_API_BASE.startswith("https://")
    assert config.FLASHHUB_API_BASE.endswith("/api/v1/repos")


def test_shared_paths_reexported_from_protocol() -> None:
    import flashcli_bundle.paths as paths

    assert config.FLASHCLI_HOME == paths.FLASHCLI_HOME
    assert config.BUNDLES_DIR == paths.BUNDLES_DIR
    assert config.MODELS_DIR == paths.MODELS_DIR
    assert config.RUNTIMES_DIR == paths.RUNTIMES_DIR
    assert config.CACHE_DIR == paths.CACHE_DIR
    assert config.FLASHHUB_API_BASE == paths.FLASHHUB_API_BASE
    assert config.SKIP_AUTO_INSTALL_ENV == paths.SKIP_AUTO_INSTALL_ENV


def test_host_only_paths() -> None:
    assert config.CONFIG_FILE == config.FLASHCLI_HOME / "config.yaml"
