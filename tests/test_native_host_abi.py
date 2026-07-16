"""Host ABI requirements derived from selected native .so (no manifest config)."""

from __future__ import annotations

from flashcli_bundle.native_host_abi import (
    HostAbiProvides,
    HostAbiRequirements,
    compare_abi,
    host_abi_fix_hints,
    max_version,
    parse_elf_version_text,
    version_at_least,
)
from flashcli_bundle.native_validate import _classify_probe_failure


_SAMPLE_READELF = """
Version symbols section '.gnu.version' contains 12 entries:
 Version needs section '.gnu.version_r' contains 2 entries:
  0x00: Version: 1  File: libstdc++.so.6  Cnt: 3
  0x10:   Name: GLIBCXX_3.4.32  Flags: none  Version: 5
  0x20:   Name: GLIBCXX_3.4.29  Flags: none  Version: 4
  0x30:   Name: CXXABI_1.3.13  Flags: none  Version: 3
  0x00: Version: 1  File: libc.so.6  Cnt: 2
  0x40:   Name: GLIBC_2.34  Flags: none  Version: 2
  0x50:   Name: GLIBC_2.17  Flags: none  Version: 1
"""


def test_parse_elf_version_text_maxima() -> None:
    req = parse_elf_version_text(_SAMPLE_READELF)
    assert req.glibc == "2.34"
    assert req.glibcxx == "3.4.32"
    assert req.cxxabi == "1.3.13"


def test_max_version_and_at_least() -> None:
    assert max_version("3.4.30", "3.4.32", "3.4.29") == "3.4.32"
    assert version_at_least("3.4.32", "3.4.32")
    assert version_at_least("3.4.32", "3.4.30")
    assert not version_at_least("3.4.30", "3.4.32")
    assert not version_at_least(None, "2.35")


def test_compare_abi_host_too_old() -> None:
    needs = HostAbiRequirements(
        glibc="2.35",
        glibcxx="3.4.32",
        sources=("flash_rt_fa2.so",),
    )
    host = HostAbiProvides(glibc="2.35", glibcxx="3.4.30", libstdcxx_path="/lib/libstdc++.so.6")
    errs = compare_abi(needs, host)
    assert len(errs) == 1
    assert "GLIBCXX_3.4.32" in errs[0]
    assert "GLIBCXX_3.4.30" in errs[0]
    assert "flash_rt_fa2.so" in errs[0]


def test_compare_abi_ok() -> None:
    needs = parse_elf_version_text(_SAMPLE_READELF)
    host = HostAbiProvides(glibc="2.39", glibcxx="3.4.32", cxxabi="1.3.15")
    assert compare_abi(needs, host) == []


def test_classify_probe_failure_host_abi() -> None:
    msg = (
        "/lib/x86_64-linux-gnu/libstdc++.so.6: version `GLIBCXX_3.4.32' "
        "not found (required by flash_rt_fa2.so)"
    )
    assert _classify_probe_failure(msg, "") == "host_abi"


def test_classify_probe_failure_cuda_still_soft_kind() -> None:
    assert (
        _classify_probe_failure("libcublas.so.13: cannot open shared object file", "")
        == "cuda_runtime"
    )


def test_host_abi_fix_hints_glibc_skips_gplusplus_13() -> None:
    text = host_abi_fix_hints(glibc_mismatch=True, libstdcxx_mismatch=True)
    assert "g++-13" not in text
    assert "glibc cannot be upgraded in place" in text


def test_host_abi_fix_hints_libstdcxx_only_mentions_gplusplus() -> None:
    text = host_abi_fix_hints(glibc_mismatch=False, libstdcxx_mismatch=True)
    assert "g++-13" in text
