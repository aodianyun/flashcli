"""Isaac-GR00T VCS pip spec helpers (groot_n17 preprocess)."""

from __future__ import annotations

from flashcli_bundle.infer.deps import (
    _is_isaac_gr00t_vcs_spec,
    _is_vcs_pip_spec,
    _parse_vcs_pip_spec,
)


def test_parse_isaac_gr00t_vcs_spec() -> None:
    spec = (
        "gr00t @ git+https://github.com/NVIDIA/Isaac-GR00T.git@"
        "ab88b50c718f6528e1df9dcbaf75865d1b604760"
    )
    name, repo, ref = _parse_vcs_pip_spec(spec)
    assert name == "gr00t"
    assert repo == "https://github.com/NVIDIA/Isaac-GR00T.git"
    assert ref == "ab88b50c718f6528e1df9dcbaf75865d1b604760"
    assert _is_vcs_pip_spec(spec)
    assert _is_isaac_gr00t_vcs_spec(spec)


def test_non_gr00t_vcs_spec_not_flagged() -> None:
    spec = "flashcli-bundle @ git+https://github.com/aodianyun/flashcli.git@main"
    assert _is_vcs_pip_spec(spec)
    assert not _is_isaac_gr00t_vcs_spec(spec)
