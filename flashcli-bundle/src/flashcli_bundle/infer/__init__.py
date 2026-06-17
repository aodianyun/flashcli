"""Bundle venv inference runtime (installed via flashcli-bundle[infer])."""

from flashcli_bundle.infer.app import execute_run, execute_serve, main

__all__ = ["execute_run", "execute_serve", "main"]
