"""FlashRT distribution CLI."""

from flashcli._version import __version__
from flashcli.runtime.mirror import apply_mirror_env

apply_mirror_env()

__all__ = ["__version__"]
