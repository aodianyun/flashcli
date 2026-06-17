"""Smoke tests for flashcli_bundle.infer module."""

from __future__ import annotations


def test_infer_module_importable() -> None:
    import flashcli_bundle.infer as infer

    assert callable(infer.main)
    assert callable(infer.execute_run)
    assert callable(infer.execute_serve)


def test_infer_app_has_run_command() -> None:
    from flashcli_bundle.infer.app import app

    names = {cmd.name for cmd in app.registered_commands if cmd.name}
    assert "run" in names
    assert "serve" in names
