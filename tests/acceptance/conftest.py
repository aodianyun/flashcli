"""Acceptance tier fixtures.

Skipped unless ``FLASHCLI_ACCEPTANCE=1`` (run ``bash scripts/verify_e2e.sh``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from helpers import ROOT


def pytest_collection_modifyitems(config, items):
    if os.environ.get("FLASHCLI_ACCEPTANCE") == "1":
        return
    skip = pytest.mark.skip(reason="acceptance tier: set FLASHCLI_ACCEPTANCE=1 (scripts/verify_e2e.sh)")
    for item in items:
        item.add_marker(skip)


def _binary(env_name: str, name: str) -> Path:
    raw = os.environ.get(env_name)
    path = Path(raw) if raw else ROOT / "dist" / "go" / name
    if not path.is_file():
        pytest.skip(f"{env_name} not found: {path} (run scripts/build_go.sh)")
    return path


@pytest.fixture(scope="session")
def flashcli_bin() -> Path:
    return _binary("FLASHCLI_GO_BIN", "flashcli-linux-amd64")


@pytest.fixture(scope="session")
def flashserver_bin() -> Path:
    return _binary("FLASHSERVER_BIN", "flashserver-linux-amd64")


@pytest.fixture(scope="session")
def home() -> Path:
    """Stable acceptance home so uv/Python/venvs are cached between runs."""
    path = Path(os.environ.get("FLASHCLI_ACCEPTANCE_HOME", "/tmp/flashcli-acceptance"))
    (path / "home").mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def cli_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "FLASHCLI_HOME": str(home / "home"),
            "FLASHCLI_BUNDLE_PIP_SPEC": str(ROOT / "flashcli-bundle"),
            "FLASHCLI_SKIP_CUDA_USERLAND": "1",
            "FLASHCLI_SKIP_WEIGHTS": "1",
            "FLASHCLI_RUNTIME_ENV_KEY": "sm89-cu124-linux-x86_64-py312",
        }
    )
    if not env.get("FLASHCLI_PY312_BIN"):
        for candidate in ("/usr/bin/python3.12", "/usr/bin/python3"):
            if Path(candidate).exists():
                env["FLASHCLI_PY312_BIN"] = candidate
                break
    # Reuse the host's mirror settings when present so venv installs stay local-fast.
    mirror = Path(os.environ.get("HOME", "~")).expanduser() / ".flashcli" / "mirror.env"
    if mirror.is_file():
        for line in mirror.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip())
    return env
