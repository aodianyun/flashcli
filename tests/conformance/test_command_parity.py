"""Anti-omission gate: the Go CLI must cover the expected command surface.

Discovers the Go command tree via cobra's hidden ``__complete`` and asserts it
covers the historical Python-host surface (kept as the contract checklist).
Adding/removing a command without updating the surface below fails here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Historical Python-host command surface (contract checklist).
PYTHON_COMMANDS = {
    "pull",
    "run",
    "serve",
    "doctor",
    "models",
    "models list",
    "models show",
    "models envs",
    "bundle",
    "bundle sync",
    "bundle clean",
    "bundle validate",
    "bundle install",
}

# Commands intentionally Go-only (no Python equivalent).
GO_ONLY_COMMANDS = {
    "version",
    "upgrade",
    "weights",
    "weights pull",
}

_COBRA_BUILTINS = {"completion", "help"}


def _complete(binary: Path, path: list[str]) -> list[str]:
    proc = subprocess.run(
        [str(binary), "__complete", *path, ""],
        capture_output=True,
        text=True,
    )
    names = []
    for line in proc.stdout.splitlines():
        if not line or line.startswith(":"):
            continue
        name = line.split("\t", 1)[0].strip()
        if name and name not in _COBRA_BUILTINS:
            names.append(name)
    return names


def _go_commands(binary: Path) -> set[str]:
    commands: set[str] = set()
    for top in _complete(binary, []):
        commands.add(top)
        for sub in _complete(binary, [top]):
            commands.add(f"{top} {sub}")
    return commands


def test_go_covers_python_commands(go_binary: Path) -> None:
    go_commands = _go_commands(go_binary)
    missing = sorted(PYTHON_COMMANDS - go_commands)
    assert not missing, f"Go host is missing Python commands: {missing}"

    undocumented = sorted(go_commands - PYTHON_COMMANDS - GO_ONLY_COMMANDS)
    assert not undocumented, (
        f"Go host has commands not accounted for in the surface map: {undocumented}. "
        f"Add them to GO_ONLY_COMMANDS if intentional."
    )
