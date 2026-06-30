"""Catalog / runtime environment keys: platform tail, os, arch, Python ABI."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

from flashcli_bundle.runtime.detect import GpuInfo

_PY_SUFFIX_RE = re.compile(r"^py(3\d{2})$")


def _parse_nvidia_segments(platform_tail: str) -> tuple[str | None, str | None]:
    sm: str | None = None
    cuda: str | None = None
    for part in platform_tail.split("-"):
        if part.startswith("sm") and len(part) > 2 and sm is None:
            sm = part[2:]
        elif part.startswith("cu") and len(part) > 2 and cuda is None:
            cuda = part[2:]
    return sm, cuda


@dataclass(frozen=True)
class RuntimeEnvKey:
    platform_tail: str
    os_name: str
    arch: str
    python_minor: str | None = None
    sm: str | None = None
    cuda_tag: str | None = None

    def catalog_name(self) -> str:
        base = f"{self.platform_tail}-{self.os_name}-{self.arch}"
        if self.python_minor:
            return f"{base}-py{self.python_minor}"
        return base


def host_python_minor() -> str:
    """Two-digit minor for catalog keys: 3.10 -> '310', 3.12 -> '312'."""
    return f"{sys.version_info.major}{sys.version_info.minor:02d}"


def variant_dir_name(gpu: GpuInfo, *, python_minor: str | None = None) -> str:
    """Environment key for this machine (NVIDIA; includes ``-pyNNN``)."""
    py = python_minor if python_minor is not None else host_python_minor()
    platform_tail = f"sm{gpu.sm}-cu{gpu.cuda_tag}"
    return RuntimeEnvKey(
        platform_tail=platform_tail,
        os_name=gpu.os_name,
        arch=gpu.arch,
        python_minor=py,
        sm=gpu.sm,
        cuda_tag=gpu.cuda_tag,
    ).catalog_name()


def parse_variant_key(name: str) -> RuntimeEnvKey:
    """Parse env keys with fixed tail ``…-{os}-{arch}-py{NNN}``."""
    parts = [p for p in name.strip().split("-") if p]
    python_minor: str | None = None
    if parts and _PY_SUFFIX_RE.match(parts[-1]):
        python_minor = parts[-1][2:]
        parts = parts[:-1]

    if len(parts) < 3:
        raise ValueError(f"invalid catalog environment key: {name!r}")

    arch = parts[-1]
    os_name = parts[-2]
    platform_tail = "-".join(parts[:-2])
    if not platform_tail:
        raise ValueError(f"invalid catalog environment key: {name!r}")

    sm, cuda = _parse_nvidia_segments(platform_tail)
    return RuntimeEnvKey(
        platform_tail=platform_tail,
        os_name=os_name,
        arch=arch,
        python_minor=python_minor,
        sm=sm,
        cuda_tag=cuda,
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
    if artifact.platform_tail == host.platform_tail:
        score += 15
        return score

    if artifact.sm and host.sm:
        if artifact.sm == host.sm:
            score += 10
        else:
            score += 6
    if artifact.cuda_tag and host.cuda_tag:
        if artifact.cuda_tag == host.cuda_tag:
            score += 5
        elif cuda_runtime_family(artifact.cuda_tag) == cuda_runtime_family(host.cuda_tag):
            score += 3
    elif artifact.platform_tail == host.platform_tail:
        score += 10
    return score


def resolve_runtime_env_key(
    runtime_map: dict[str, str],
    host_key: str,
) -> str | None:
    """Pick the best ``runtime`` map key for *host_key* (exact or fuzzy)."""
    override = os.environ.get("FLASHCLI_RUNTIME_ENV_KEY", "").strip()
    if override and override in runtime_map:
        return override
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
