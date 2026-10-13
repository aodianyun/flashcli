"""Flag-parity gate: the Go host must accept the historical Python-host flags.

Complements ``test_command_parity`` (command surface). Encodes the flags each
command accepted in the Python host; documented Go differences are listed in
``INTENTIONAL_DIFFERENCES``.

Historical Python host flags:
  pull            --no-auto-install --quiet/-q
  bundle sync     --force --quiet/-q
  bundle clean    --all --full --flashhub-cache
  bundle validate --skip-abi-probe
  bundle install  --force --quiet/-q
  root            --version/-V
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# command -> required flag tokens (must all appear in `--help`)
FLAG_CASES = {
    ("pull",): ["--no-auto-install", "--quiet", "-q"],
    ("bundle", "sync"): ["--force", "--quiet", "-q"],
    ("bundle", "clean"): ["--all", "--full", "--flashhub-cache"],
    ("bundle", "validate"): ["--skip-abi-probe"],
    ("bundle", "install"): ["--force", "--quiet", "-q"],
}

# Python `doctor --install/--force` installed *host Python* deps; the Go host is
# a static binary, so those are intentionally absent. Go adds `version`,
# `upgrade`, `weights` and some extra flags.
INTENTIONAL_DIFFERENCES = {
    ("doctor",): "no host Python deps to install; OS tools via install.sh",
}


def _help(binary: Path, cmd: tuple[str, ...]) -> str:
    proc = subprocess.run(
        [str(binary), *cmd, "--help"],
        capture_output=True,
        text=True,
    )
    return proc.stdout + proc.stderr


def test_flag_parity(go_binary: Path) -> None:
    for cmd, flags in FLAG_CASES.items():
        if cmd in INTENTIONAL_DIFFERENCES:
            continue
        out = _help(go_binary, cmd)
        for flag in flags:
            assert flag in out, f"{' '.join(cmd)} --help missing {flag}\n{out}"


def test_root_version_flags(go_binary: Path) -> None:
    for flag in ("--version", "-V"):
        proc = subprocess.run([str(go_binary), flag], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip(), f"{flag} produced no version"
