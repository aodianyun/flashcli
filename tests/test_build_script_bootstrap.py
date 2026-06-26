"""Build-script bootstrap: no installed flashcli required."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_LIB = Path(__file__).resolve().parents[1] / "scripts" / "lib"
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

from flashcli_bundle_path import ensure_flashcli_bundle_on_path  # noqa: E402


def test_generate_runtime_manifest_imports_without_flashcli_package() -> None:
    ensure_flashcli_bundle_on_path(Path(__file__).resolve().parents[1])
    from flashcli_bundle.native_naming import (  # noqa: F401
        parse_native_tag_from_filename,
    )

    parsed = parse_native_tag_from_filename(
        "flash_rt_qwen3_vl_kernels-dev-sm120-cu130-linux-x86_64-py312.so"
    )
    assert parsed is not None
    assert parsed.catalog_key() == "sm120-cu130-linux-x86_64-py312"
