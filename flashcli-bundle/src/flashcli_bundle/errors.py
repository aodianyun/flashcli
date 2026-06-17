"""Shared flashcli-bundle errors."""


class BundleNotReadyError(RuntimeError):
    exit_code = 2
