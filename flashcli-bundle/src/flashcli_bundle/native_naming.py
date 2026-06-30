"""Canonical filenames and host selection for FlashRT native ``.so`` artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from flashcli_bundle.runtime_env import (
    RuntimeEnvKey,
    cuda_runtime_family,
    host_python_minor,
    parse_variant_key,
    score_env_key_match,
    variant_dir_name,
)
from flashcli_bundle.runtime.detect import GpuInfo

DEFAULT_NATIVE_LIB = "lib"  # build-time staging only; runtime loads runtime/<env-key>/

_ABI_SANITIZE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class ParsedNativeTag:
    module_base: str
    flashrt_abi: str
    env_key: str
    sm: str | None = None
    cuda_tag: str | None = None
    os_name: str = ""
    arch: str = ""
    python_minor: str = ""

    def catalog_key(self) -> str:
        return self.env_key

    @classmethod
    def from_parts(
        cls,
        *,
        module_base: str,
        flashrt_abi: str,
        env_key: str,
    ) -> ParsedNativeTag:
        env = parse_variant_key(env_key)
        return cls(
            module_base=module_base,
            flashrt_abi=flashrt_abi,
            env_key=env_key,
            sm=env.sm,
            cuda_tag=env.cuda_tag,
            os_name=env.os_name,
            arch=env.arch,
            python_minor=env.python_minor or "",
        )


class NativeEnvironmentNotSupportedError(RuntimeError):
    """No ``runtime/<env-key>/*.so`` artifact matches this machine."""

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
    """Tag suffix: ``{abi}-{env_key}`` (NVIDIA ``sm``/``cu`` platform tail)."""
    sm = str(sm).strip().lstrip("sSmM")
    cuda_tag = str(cuda_tag).strip().lstrip("cCuU")
    py = str(python_minor).strip().lstrip("pPyY")
    if py.isdigit() and len(py) == 1:
        py = f"3{py}0"
    env_key = RuntimeEnvKey(
        platform_tail=f"sm{sm}-cu{cuda_tag}",
        os_name=os_name,
        arch=arch,
        python_minor=py,
        sm=sm,
        cuda_tag=cuda_tag,
    ).catalog_name()
    return f"{flashrt_abi}-{env_key}"


def native_so_filename(module_base: str, tag: str) -> str:
    return f"{module_base}-{tag}.so"


_KNOWN_OS = frozenset({"linux", "darwin", "win32", "windows"})
_KNOWN_ARCH = frozenset({"x86_64", "aarch64", "arm64"})


def infer_env_key_from_native_stem(stem: str) -> str | None:
    """Extract env key suffix from ``{module}-{abi}-{env_key}`` or ``{abi}-{env_key}``."""
    parts = [p for p in stem.split("-") if p]
    if len(parts) < 4:
        return None
    starts = (2, 1) if len(parts) >= 7 else (1, 2)
    for start in starts:
        if len(parts) <= start:
            continue
        candidate = "-".join(parts[start:])
        try:
            env = parse_variant_key(candidate)
        except ValueError:
            continue
        if env.os_name in _KNOWN_OS and env.arch in _KNOWN_ARCH:
            return candidate
    for i in range(len(parts) - 3, 0, -1):
        candidate = "-".join(parts[i:])
        try:
            env = parse_variant_key(candidate)
        except ValueError:
            continue
        if env.os_name in _KNOWN_OS and env.arch in _KNOWN_ARCH:
            return candidate
    return None


def resolve_env_key_for_native_dir(native_dir: Path, env_key: str | None = None) -> str | None:
    if env_key:
        return env_key
    name = native_dir.name.strip()
    if not name or name in ("lib", "runtime", ".", ".."):
        return None
    try:
        parse_variant_key(name)
    except ValueError:
        return None
    return name


def parse_native_artifact(
    filename: str,
    *,
    env_key: str,
) -> ParsedNativeTag | None:
    """Parse ``{module_base}-{flashrt_abi}-{env_key}.so``."""
    stem = Path(filename).name
    if stem.endswith(".so"):
        stem = stem[: -len(".so")]
    suffix = f"-{env_key}"
    if not stem.endswith(suffix):
        return None
    module_and_abi = stem[: -len(suffix)]
    if not module_and_abi or "-" not in module_and_abi:
        return None
    module_base, _, flashrt_abi = module_and_abi.rpartition("-")
    if not module_base or not flashrt_abi:
        return None
    try:
        return ParsedNativeTag.from_parts(
            module_base=module_base,
            flashrt_abi=flashrt_abi,
            env_key=env_key,
        )
    except ValueError:
        return None


def logical_native_module_name(filename: str, *, env_key: str | None = None) -> str:
    """Import name for pybind (``flash_rt_kernels``, not the full tagged stem)."""
    key = env_key or infer_env_key_from_native_stem(
        Path(filename).name[: -len(".so")] if filename.endswith(".so") else filename
    )
    if key:
        parsed = parse_native_artifact(filename, env_key=key)
        if parsed is not None:
            return parsed.module_base
    stem = Path(filename).name
    if stem.endswith(".so"):
        stem = stem[: -len(".so")]
    return stem


def parse_native_tag_suffix(tag_suffix: str) -> ParsedNativeTag | None:
    """Parse legacy ``{abi}-{env_key}`` tag suffix (build scripts)."""
    env_key = infer_env_key_from_native_stem(tag_suffix.strip())
    if env_key is None:
        return None
    abi = tag_suffix[: -(len(env_key) + 1)].strip("-")
    if not abi:
        abi = "dev"
    return ParsedNativeTag.from_parts(
        module_base="",
        flashrt_abi=abi,
        env_key=env_key,
    )


def parse_native_tag_from_filename(
    filename: str,
    *,
    env_key: str | None = None,
) -> ParsedNativeTag | None:
    stem = Path(filename).name
    if stem.endswith(".so"):
        stem = stem[: -len(".so")]
    key = env_key or infer_env_key_from_native_stem(stem)
    if key is None:
        return None
    return parse_native_artifact(f"{stem}.so", env_key=key)


def discover_native_module_bases(
    native_dir: Path,
    env_key: str | None = None,
) -> tuple[str, ...]:
    """Return ``module_base`` names from all tagged ``*.so`` in the cell directory."""
    if not native_dir.is_dir():
        return ()
    key = resolve_env_key_for_native_dir(native_dir, env_key)
    seen: set[str] = set()
    for path in sorted(native_dir.glob("*.so")):
        if key:
            parsed = parse_native_artifact(path.name, env_key=key)
        else:
            parsed = parse_native_tag_from_filename(path.name)
        if parsed is not None and parsed.module_base:
            seen.add(parsed.module_base)
    return tuple(sorted(seen))


def bundle_native_lib_dir(bundle_root: Path, rel: str | None = None) -> Path:
    sub = (rel or DEFAULT_NATIVE_LIB).strip().strip("/")
    return (bundle_root.resolve() / sub).resolve()


def bundle_uses_runtime_matrix(raw: dict) -> bool:
    return isinstance(raw.get("runtime"), dict) and bool(raw["runtime"])


def native_dir_has_tagged_native_artifacts(
    native_dir: Path,
    env_key: str | None = None,
) -> bool:
    """True when a native dir holds ``*-{env_key}.so`` or inferrable env tags."""
    if not native_dir.is_dir():
        return False
    key = resolve_env_key_for_native_dir(native_dir, env_key)
    for path in native_dir.glob("*.so"):
        if key and parse_native_artifact(path.name, env_key=key):
            return True
        if parse_native_tag_from_filename(path.name) is not None:
            return True
    return False


def lib_dir_has_tagged_native_artifacts(lib_dir: Path) -> bool:
    return native_dir_has_tagged_native_artifacts(lib_dir)


def host_runtime_env_key(gpu: GpuInfo, *, python_minor: str | None = None) -> RuntimeEnvKey:
    return parse_variant_key(variant_dir_name(gpu, python_minor=python_minor))


def _sm_artifact_compatible(
    host_sm: str | None, artifact_sm: str | None, allowed_sm: list[str] | None
) -> bool:
    if not host_sm or not artifact_sm:
        return True
    if artifact_sm == host_sm:
        return True
    if allowed_sm:
        allowed = {str(s).strip() for s in allowed_sm}
        return host_sm in allowed and artifact_sm in allowed
    return True


def score_native_tag(
    artifact: ParsedNativeTag,
    host: RuntimeEnvKey,
    *,
    allowed_sm: list[str] | None = None,
) -> int:
    if artifact.env_key == host.catalog_name():
        return 100
    if artifact.python_minor and artifact.python_minor != host.python_minor:
        return 0
    if artifact.os_name and (
        artifact.os_name != host.os_name or artifact.arch != host.arch
    ):
        return 0
    if (
        artifact.cuda_tag
        and host.cuda_tag
        and artifact.cuda_tag != host.cuda_tag
        and cuda_runtime_family(artifact.cuda_tag)
        != cuda_runtime_family(host.cuda_tag)
    ):
        return 0
    if not _sm_artifact_compatible(host.sm, artifact.sm, allowed_sm):
        return 0
    try:
        artifact_env = parse_variant_key(artifact.env_key)
    except ValueError:
        return 0
    return score_env_key_match(artifact_env, host)


def list_native_artifacts(
    lib_dir: Path,
    env_key: str | None = None,
) -> dict[str, list[tuple[ParsedNativeTag, Path]]]:
    """Map module_base -> [(parsed tag, path), ...]."""
    out: dict[str, list[tuple[ParsedNativeTag, Path]]] = {}
    if not lib_dir.is_dir():
        return out
    key = resolve_env_key_for_native_dir(lib_dir, env_key)
    for path in sorted(lib_dir.glob("*.so")):
        if key:
            parsed = parse_native_artifact(path.name, env_key=key)
        else:
            parsed = parse_native_tag_from_filename(path.name)
        if parsed is None or not parsed.module_base:
            continue
        out.setdefault(parsed.module_base, []).append((parsed, path))
    return out


def _pick_best_artifact(
    items: list[tuple[ParsedNativeTag, Path]],
) -> Path:
    """Choose one artifact when multiple ABI builds share a module_base."""
    ranked = sorted(items, key=lambda item: (item[0].flashrt_abi, item[1].name))
    return ranked[0][1]


def select_native_module_for_host(
    lib_dir: Path,
    module_base: str,
    gpu: GpuInfo,
    *,
    allowed_sm: list[str] | None = None,
    python_minor: str | None = None,
    env_key: str | None = None,
) -> Path:
    key = resolve_env_key_for_native_dir(lib_dir, env_key)
    if key:
        arts = list_native_artifacts(lib_dir, env_key=key).get(module_base, [])
        if arts:
            return _pick_best_artifact(arts)
        raise NativeEnvironmentNotSupportedError(
            module_base=module_base,
            wanted=key,
            lib_dir=lib_dir,
            available=list(list_native_artifacts(lib_dir, env_key=key)),
            gpu=gpu,
        )

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
                key_name = parsed.catalog_key()
                if key_name not in avail_keys:
                    avail_keys.append(key_name)
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
    env_key: str | None = None,
) -> list[Path]:
    """All matching ``.so`` paths for this host, best-first."""
    key = resolve_env_key_for_native_dir(lib_dir, env_key)
    if key:
        arts = list_native_artifacts(lib_dir, env_key=key).get(module_base, [])
        if not arts:
            return []
        return [_pick_best_artifact(arts)]

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
    native_dir_rel: str | None = None,
    native_lib_rel: str | None = None,
    allowed_sm: list[str] | None = None,
    required_modules: tuple[str, ...] | None = None,
    python_minor: str | None = None,
) -> dict[str, Path]:
    """Pick one ``.so`` per module present in the runtime cell (or *required_modules*)."""
    rel = native_dir_rel if native_dir_rel is not None else native_lib_rel
    native_dir = bundle_native_lib_dir(bundle_root, rel)
    env_key = resolve_env_key_for_native_dir(native_dir)
    if not native_dir.is_dir():
        raise NativeEnvironmentNotSupportedError(
            module_base="native",
            wanted=host_runtime_env_key(gpu).catalog_name(),
            lib_dir=native_dir,
            available=[],
            gpu=gpu,
        )
    modules = (
        required_modules
        if required_modules is not None
        else discover_native_module_bases(native_dir, env_key=env_key)
    )
    if not modules:
        raise NativeEnvironmentNotSupportedError(
            module_base="native",
            wanted=env_key or host_runtime_env_key(gpu).catalog_name(),
            lib_dir=native_dir,
            available=[],
            gpu=gpu,
        )
    resolved: dict[str, Path] = {}
    for base in modules:
        resolved[base] = select_native_module_for_host(
            native_dir,
            base,
            gpu,
            allowed_sm=allowed_sm,
            python_minor=python_minor,
            env_key=env_key,
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
