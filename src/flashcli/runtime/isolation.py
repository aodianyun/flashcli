"""Host vs bundle Python environment isolation invariants.

Architecture (non-negotiable):
- Host venv: flashcli CLI, huggingface_hub, weight pull, FlashHub sync.
- Bundle venv: flashcli-bundle protocol, manifest python_dependencies, infer HTTP helpers.
- Cross-boundary: bundle process may import **host flashcli** (``runtime.infer`` only) via
  :func:`host_flashcli_import_root` — never the full host ``site-packages``.
"""

from __future__ import annotations

from pathlib import Path

# Host-only packages that must never appear as import roots/siblings for bundle re-exec.
_HOST_ONLY_SIBLINGS = frozenset({"huggingface_hub", "huggingface-hub"})


class HostBundleIsolationError(RuntimeError):
    """Bundle re-exec would see host packages outside ``flashcli``."""


def validate_host_import_root(root: Path) -> None:
    """Fail fast if *root* exposes more than the host ``flashcli`` package.

    Call from :func:`host_flashcli_import_root` and ``infer_launch`` so regressions
    (e.g. prepending ``site-packages``) break at startup, not inside ``transformers``.
    """
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise HostBundleIsolationError(f"Host import root is not a directory: {resolved}")

    if resolved.name == "site-packages":
        raise HostBundleIsolationError(
            f"Host import root must not be site-packages: {resolved}\n"
            "Use host_flashcli_import_root() (host-import shim or editable src/)."
        )

    children = [p for p in resolved.iterdir() if not p.name.startswith(".")]
    names = {p.name for p in children}

    for forbidden in _HOST_ONLY_SIBLINGS:
        if forbidden in names:
            raise HostBundleIsolationError(
                f"Host import root {resolved} exposes host-only package {forbidden!r}. "
                "Bundle and flashcli environments must stay isolated."
            )

    # Editable: src/ contains flashcli/
    if (resolved / "flashcli").is_dir():
        extra = names - {"flashcli", "flashcli_bundle", "flashcli-bundle"}
        if extra - {n for n in extra if n.endswith(".dist-info") or n.endswith(".egg-link")}:
            # Allow dist-info only; any other top-level package dir is suspicious.
            pkg_dirs = [
                n
                for n in extra
                if (resolved / n).is_dir()
                and not n.endswith(".dist-info")
                and n != "flashcli_bundle"
            ]
            if pkg_dirs:
                raise HostBundleIsolationError(
                    f"Host import root {resolved} exposes extra packages: {sorted(pkg_dirs)}"
                )
        return

    # Wheel shim: host-import/ contains flashcli -> symlink only
    if names <= {"flashcli"} or names == {"flashcli"}:
        link = resolved / "flashcli"
        if not link.exists():
            raise HostBundleIsolationError(
                f"Host import root {resolved} missing flashcli/ entry"
            )
        return

    raise HostBundleIsolationError(
        f"Host import root {resolved} has unexpected entries: {sorted(names)}"
    )
