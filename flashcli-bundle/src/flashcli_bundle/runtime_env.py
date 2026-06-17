"""Catalog / runtime environment keys: sm, cuda, os, arch, Python ABI."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from flashcli_bundle.runtime.detect import GpuInfo

_PY_SUFFIX_RE = re.compile(r"^py(3\d{2})$")


@dataclass(frozen=True)
class RuntimeEnvKey:
    sm: str
    cuda_tag: str
    os_name: str
    arch: str
    python_minor: str | None = None  # e.g. "310" for Python 3.10

    def catalog_name(self) -> str:
        base = f"sm{self.sm}-cu{self.cuda_tag}-{self.os_name}-{self.arch}"
        if self.python_minor:
            return f"{base}-py{self.python_minor}"
        return base


def host_python_minor() -> str:
    """Two-digit minor for catalog keys: 3.10 -> '310', 3.12 -> '312'."""
    return f"{sys.version_info.major}{sys.version_info.minor:02d}"


def variant_dir_name(gpu: GpuInfo, *, python_minor: str | None = None) -> str:
    """Environment key for this machine (includes ``-pyNNN`` when python_minor set)."""
    py = python_minor if python_minor is not None else host_python_minor()
    return RuntimeEnvKey(
        sm=gpu.sm,
        cuda_tag=gpu.cuda_tag,
        os_name=gpu.os_name,
        arch=gpu.arch,
        python_minor=py,
    ).catalog_name()


def parse_variant_key(name: str) -> RuntimeEnvKey:
    """Parse ``sm89-cu124-linux-x86_64-py310`` (optional trailing ``-pyNNN``)."""
    parts = [p for p in name.strip().split("-") if p]
    python_minor: str | None = None
    if parts and _PY_SUFFIX_RE.match(parts[-1]):
        python_minor = parts[-1][2:]  # drop "py" prefix -> "310"
        parts = parts[:-1]

    sm = cuda = None
    os_name: str | None = None
    arch: str | None = None
    for part in parts:
        if part.startswith("sm") and len(part) > 2:
            sm = part[2:]
        elif part.startswith("cu") and len(part) > 2:
            cuda = part[2:]
    if len(parts) >= 2:
        os_name = parts[-2]
        arch = parts[-1]

    if not sm or not cuda or not os_name or not arch:
        raise ValueError(f"invalid catalog environment key: {name!r}")

    return RuntimeEnvKey(
        sm=sm,
        cuda_tag=cuda,
        os_name=os_name,
        arch=arch,
        python_minor=python_minor,
    )


def key_has_python_tag(name: str) -> bool:
    return bool(re.search(r"-py3\d{2}$", name.strip()))


def cuda_runtime_family(cuda_tag: str) -> str:
    """Group CUDA tags for fuzzy catalog match (12.x vs 13.x runtime)."""
    tag = cuda_tag.strip()
    if tag.startswith("13") or tag in ("130",):
        return "13"
    if tag.startswith("12") or tag in ("124", "128", "120"):
        return "12"
    return tag[:2] if len(tag) >= 2 else tag


def score_env_key_match(artifact: RuntimeEnvKey, host: RuntimeEnvKey) -> int:
    """Rank manifest ``runtime`` keys against this machine (higher = better)."""
    if artifact.python_minor != host.python_minor:
        return 0
    if artifact.os_name != host.os_name or artifact.arch != host.arch:
        return 0
    score = 20
    if artifact.sm == host.sm:
        score += 10
    else:
        score += 6
    if artifact.cuda_tag == host.cuda_tag:
        score += 5
    elif cuda_runtime_family(artifact.cuda_tag) == cuda_runtime_family(host.cuda_tag):
        score += 3
    return score


def resolve_runtime_env_key(
    runtime_map: dict[str, str],
    host_key: str,
) -> str | None:
    """Pick the best ``runtime`` map key for *host_key* (exact or fuzzy)."""
    if host_key in runtime_map:
        return host_key
    try:
        host = parse_variant_key(host_key)
    except ValueError:
        return None
    best_key: str | None = None
    best_score = 0
    for key in runtime_map:
        try:
            artifact = parse_variant_key(key)
        except ValueError:
            continue
        score = score_env_key_match(artifact, host)
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_score > 0 else None
