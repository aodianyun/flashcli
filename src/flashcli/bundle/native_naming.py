"""Canonical filenames and host selection for FlashRT native ``.so`` artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from flashcli.bundle.runtime_env import (
    RuntimeEnvKey,
    cuda_runtime_family,
    host_python_minor,
    parse_variant_key,
    variant_dir_name,
)
from flashcli.runtime.detect import GpuInfo

# Longest first for prefix matching in logical_native_module_name.
NATIVE_MODULE_BASES: tuple[str, ...] = (
    "libfmha_fp16_strided",
    "flash_rt_kernels",
    "flash_rt_fa2",
    "flash_rt_fp4",
)

DEFAULT_NATIVE_LIB = "lib"
_REQUIRED_PI05_MODULES = ("flash_rt_kernels", "flash_rt_fa2")

_ABI_SANITIZE = re.compile(r"[^a-zA-Z0-9._-]+")
_PY_TAIL_RE = re.compile(r"-py(3\d{2})$")


@dataclass(frozen=True)
class ParsedNativeTag:
    flashrt_abi: str
    sm: str
    cuda_tag: str
    os_name: str
    arch: str
    python_minor: str

    def catalog_key(self) -> str:
        return (
            f"sm{self.sm}-cu{self.cuda_tag}-{self.os_name}-"
            f"{self.arch}-py{self.python_minor}"
        )


class NativeEnvironmentNotSupportedError(RuntimeError):
    """No ``lib/*.so`` artifact matches this machine."""

    def __init__(
        self,
        *,
        module_base: str,
        wanted: str,
        lib_dir: Path,
        available: list[str],
        gpu: GpuInfo | None = None,
    ) -> None:
        self.module_base = module_base
        self.wanted = wanted
        self.lib_dir = lib_dir
        self.available = available
        self.gpu = gpu
        avail = ", ".join(available) if available else "(none)"
        super().__init__(
            f"No native library for {module_base!r} matching environment {wanted!r} "
            f"under {lib_dir}.\n"
            f"  Available artifacts: {avail}\n"
            f"  Build or download a bundle that includes this matrix cell, "
            f"or use a matching Python/CUDA/GPU combination."
        )


def sanitize_flashrt_abi(flashrt_tag: str, *, git_commit: str = "") -> str:
    """Short, filesystem-safe FlashRT ABI segment (tag or commit)."""
    t = _ABI_SANITIZE.sub("-", (flashrt_tag or "").strip()).strip("-")
    if not t or len(t) > 40:
        commit = (git_commit or "unknown").strip()
        t = commit[:12] if commit else "dev"
    return t


def native_artifact_tag(
    *,
    flashrt_abi: str,
    sm: str,
    cuda_tag: str,
    os_name: str,
    arch: str,
    python_minor: str,
) -> str:
    """Tag suffix: ``{abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}``."""
    sm = str(sm).strip().lstrip("sSmM")
    cuda_tag = str(cuda_tag).strip().lstrip("cCuU")
    py = str(python_minor).strip().lstrip("pPyY")
    if py.isdigit() and len(py) == 1:
        py = f"3{py}0"
    return f"{flashrt_abi}-sm{sm}-cu{cuda_tag}-{os_name}-{arch}-py{py}"


def native_so_filename(module_base: str, tag: str) -> str:
    return f"{module_base}-{tag}.so"


def logical_native_module_name(filename: str) -> str:
    """Import name for pybind (``flash_rt_kernels``, not the full tagged stem)."""
    stem = Path(filename).name
    if stem.endswith(".so"):
        stem = stem[: -len(".so")]
    for base in NATIVE_MODULE_BASES:
        if stem == base or stem.startswith(f"{base}-"):
            return base
    return stem


def parse_native_tag_suffix(tag_suffix: str) -> ParsedNativeTag | None:
    """Parse ``{abi}-sm{SM}-cu{CUDA}-{os}-{arch}-py{PY}`` (abi may contain dashes)."""
    suffix = tag_suffix.strip()
    m = _PY_TAIL_RE.search(suffix)
    if not m:
        return None
    python_minor = m.group(1)
    rest = suffix[: m.start()]
    parts = [p for p in rest.split("-") if p]
    if len(parts) < 4:
        return None

    arch = parts[-1]
    os_name = parts[-2]
    sm: str | None = None
    cuda: str | None = None
    abi_parts: list[str] = []
    for part in parts[:-2]:
        if part.startswith("sm") and len(part) > 2 and sm is None:
            sm = part[2:]
        elif part.startswith("cu") and len(part) > 2 and cuda is None:
            cuda = part[2:]
        else:
            abi_parts.append(part)
    if not sm or not cuda:
        return None
    flashrt_abi = "-".join(abi_parts) if abi_parts else "dev"
    return ParsedNativeTag(
        flashrt_abi=flashrt_abi,
        sm=sm,
        cuda_tag=cuda,
        os_name=os_name,
        arch=arch,
        python_minor=python_minor,
    )


def parse_native_tag_from_filename(filename: str) -> ParsedNativeTag | None:
    stem = Path(filename).name
    if stem.endswith(".so"):
        stem = stem[: -len(".so")]
    for base in NATIVE_MODULE_BASES:
        prefix = f"{base}-"
        if stem.startswith(prefix):
            return parse_native_tag_suffix(stem[len(prefix) :])
    return None


def bundle_native_lib_dir(bundle_root: Path, rel: str | None = None) -> Path:
    sub = (rel or DEFAULT_NATIVE_LIB).strip().strip("/")
    return (bundle_root.resolve() / sub).resolve()


def bundle_uses_native_matrix(raw: dict) -> bool:
    if raw.get("native_layout") == "matrix":
        return True
    if raw.get("native_matrix"):
        return True
    return False


def host_runtime_env_key(gpu: GpuInfo, *, python_minor: str | None = None) -> RuntimeEnvKey:
    return parse_variant_key(variant_dir_name(gpu, python_minor=python_minor))


def _sm_artifact_compatible(
    host_sm: str, artifact_sm: str, allowed_sm: list[str] | None
) -> bool:
    if artifact_sm == host_sm:
        return True
    if not allowed_sm:
        return False
    allowed = {str(s).strip() for s in allowed_sm}
    return host_sm in allowed and artifact_sm in allowed


def score_native_tag(
    artifact: ParsedNativeTag,
    host: RuntimeEnvKey,
    *,
    allowed_sm: list[str] | None = None,
) -> int:
    if artifact.python_minor != host.python_minor:
        return 0
    if not _sm_artifact_compatible(host.sm, artifact.sm, allowed_sm):
        return 0
    if artifact.os_name != host.os_name or artifact.arch != host.arch:
        return 0

    score = 20  # exact python
    if artifact.sm == host.sm:
        score += 10
    else:
        score += 6  # e.g. host sm120 + artifact sm89 both in requires.sm
    if artifact.cuda_tag == host.cuda_tag:
        score += 5
    elif cuda_runtime_family(artifact.cuda_tag) == cuda_runtime_family(host.cuda_tag):
        score += 3
    return score


def list_native_artifacts(lib_dir: Path) -> dict[str, list[tuple[ParsedNativeTag, Path]]]:
    """Map module_base -> [(parsed tag, path), ...]."""
    out: dict[str, list[tuple[ParsedNativeTag, Path]]] = {b: [] for b in NATIVE_MODULE_BASES}
    if not lib_dir.is_dir():
        return out
    for path in sorted(lib_dir.glob("*.so")):
        parsed = parse_native_tag_from_filename(path.name)
        if parsed is None:
            continue
        base = logical_native_module_name(path.name)
        out.setdefault(base, []).append((parsed, path))
    return out


def select_native_module_for_host(
    lib_dir: Path,
    module_base: str,
    gpu: GpuInfo,
    *,
    allowed_sm: list[str] | None = None,
    python_minor: str | None = None,
) -> Path:
    host = host_runtime_env_key(gpu, python_minor=python_minor or host_python_minor())
    wanted = host.catalog_name()
    ranked: list[tuple[int, str, Path]] = []
    for parsed, path in list_native_artifacts(lib_dir).get(module_base, []):
        score = score_native_tag(parsed, host, allowed_sm=allowed_sm)
        if score > 0:
            ranked.append((score, parsed.catalog_key(), path))
    if not ranked:
        avail_keys: list[str] = []
        for _base, items in list_native_artifacts(lib_dir).items():
            for parsed, _path in items:
                key = parsed.catalog_key()
                if key not in avail_keys:
                    avail_keys.append(key)
        raise NativeEnvironmentNotSupportedError(
            module_base=module_base,
            wanted=wanted,
            lib_dir=lib_dir,
            available=avail_keys,
            gpu=gpu,
        )
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][2]


def select_native_module_ranked(
    lib_dir: Path,
    module_base: str,
    gpu: GpuInfo,
    *,
    allowed_sm: list[str] | None = None,
    python_minor: str | None = None,
) -> list[Path]:
    """All matching ``.so`` paths for this host, best-first."""
    host = host_runtime_env_key(gpu, python_minor=python_minor or host_python_minor())
    ranked: list[tuple[int, str, Path]] = []
    for parsed, path in list_native_artifacts(lib_dir).get(module_base, []):
        score = score_native_tag(parsed, host, allowed_sm=allowed_sm)
        if score > 0:
            ranked.append((score, parsed.catalog_key(), path))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [path for _score, _key, path in ranked]


def resolve_native_modules_for_host(
    bundle_root: Path,
    gpu: GpuInfo,
    *,
    native_lib_rel: str | None = None,
    allowed_sm: list[str] | None = None,
    required_modules: tuple[str, ...] = _REQUIRED_PI05_MODULES,
    python_minor: str | None = None,
) -> dict[str, Path]:
    """Pick one ``.so`` per required module for this host."""
    lib_dir = bundle_native_lib_dir(bundle_root, native_lib_rel)
    if not lib_dir.is_dir():
        raise NativeEnvironmentNotSupportedError(
            module_base=required_modules[0],
            wanted=host_runtime_env_key(gpu).catalog_name(),
            lib_dir=lib_dir,
            available=[],
            gpu=gpu,
        )
    resolved: dict[str, Path] = {}
    for base in required_modules:
        resolved[base] = select_native_module_for_host(
            lib_dir,
            base,
            gpu,
            allowed_sm=allowed_sm,
            python_minor=python_minor,
        )
    return resolved


def find_native_so_files(
    bundle_root: Path,
    module_base: str,
    *,
    artifact_tag: str | None = None,
    native_lib_rel: str | None = None,
) -> list[Path]:
    """Return matching ``.so`` paths under bundle ``lib/`` (v2 layout)."""
    lib_dir = bundle_native_lib_dir(bundle_root, native_lib_rel)
    if not lib_dir.is_dir():
        return []
    if artifact_tag:
        exact = lib_dir / native_so_filename(module_base, artifact_tag)
        if exact.is_file():
            return [exact]
    matches = sorted(lib_dir.glob(f"{module_base}-*.so"))
    return [p for p in matches if p.is_file()]


def pick_native_so(
    bundle_root: Path,
    module_base: str,
    *,
    artifact_tag: str | None = None,
    native_lib_rel: str | None = None,
) -> Path | None:
    found = find_native_so_files(
        bundle_root,
        module_base,
        artifact_tag=artifact_tag,
        native_lib_rel=native_lib_rel,
    )
    return found[0] if found else None
