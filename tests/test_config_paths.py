"""Tests for models.yaml path resolution (pip vs editable)."""

from __future__ import annotations

from pathlib import Path

import flashcli.config as config


def test_models_yaml_exists():
    assert config.MODELS_YAML.is_file()


def test_catalog_is_only_source_of_truth():
    catalog = Path(__file__).resolve().parents[1] / "src" / "flashcli" / "catalog" / "models.yaml"
    assert catalog.is_file()
    assert config.MODELS_YAML.resolve() == catalog.resolve()


def test_package_root_is_directory():
    root = config.package_root()
    assert root.is_dir()
