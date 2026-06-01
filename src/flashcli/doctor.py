"""Environment diagnostics and install."""

from __future__ import annotations

from flashcli import config
from flashcli.deps import (
    bundle_python_stack_satisfied,
    flashcli_core_stack_satisfied,
    flashcli_serve_stack_satisfied,
)
from flashcli.env import ensure_environment
from flashcli.models.hf_hub import hub_cli_on_path
from flashcli.runtime.detect import detect_gpu
from flashcli.runtime.mirror import mirror_status_lines


def run_check(*, quiet: bool = False) -> int:
    """Print environment status; return 0 if healthy, 1 if issues."""
    issues = 0
    gpu = detect_gpu()
    if gpu is None:
        print("[!] No NVIDIA GPU detected (nvidia-smi).")
        issues += 1
    else:
        print(f"[ok] GPU: {gpu.gpu_name} (sm{gpu.sm}, cuda_tag={gpu.cuda_tag})")
        print(f"     Recommended torch index: {gpu.recommended_torch_index}")

    if flashcli_core_stack_satisfied():
        print("[ok] flashcli core dependencies (typer, huggingface_hub, …)")
    else:
        print("[!] flashcli core dependencies incomplete. Run: flashcli doctor --install")
        issues += 1

    if flashcli_serve_stack_satisfied():
        print("[ok] flashcli serve dependencies (fastapi, uvicorn)")
    else:
        print(
            "[!] flashcli serve dependencies incomplete "
            "(needed for `flashcli serve`). Run: flashcli doctor --install"
        )
        issues += 1

    hf_cli = hub_cli_on_path()
    if hf_cli:
        print(f"[ok] Hugging Face Hub CLI: {hf_cli}")
    else:
        import sys

        import importlib.util

        if importlib.util.find_spec("huggingface_hub") is not None:
            print(
                "[ok] Hugging Face Hub CLI: "
                f"{sys.executable} -m huggingface_hub.cli.hf (not on PATH; flashcli still works)"
            )
        else:
            print("[!] huggingface_hub missing. Run: flashcli doctor --install")
            issues += 1

    hf_ep = __import__("os").environ.get("HF_ENDPOINT", "").strip()
    if hf_ep:
        print(f"[ok] HF_ENDPOINT={hf_ep}")
    elif not quiet:
        print(
            "[i] HF_ENDPOINT not set — flashcli tries huggingface.co then hf-mirror.com. "
            "For restricted networks: export HF_ENDPOINT=https://hf-mirror.com"
        )

    if not quiet:
        for line in mirror_status_lines():
            print(line)

    from flashcli.bundle.activate import active_bundle

    b = active_bundle()
    if b is not None:
        print(f"[ok] Active model bundle: {b.bundle_root}")
        if bundle_python_stack_satisfied(bundle_root=b.bundle_root):
            print("[ok] Bundle inference Python stack")
        else:
            print("[!] Bundle inference Python stack incomplete.")
            issues += 1
    else:
        print(
            "[i] No active model bundle (expected until run/serve). "
            "Use: flashcli bundle install <bundle>"
        )

    if not quiet and config.FLASHCLI_HOME.is_dir():
        print(f"     Home: {config.FLASHCLI_HOME}")
    return issues


def run_install(
    *,
    quiet: bool = False,
    force: bool = False,
) -> None:
    ensure_environment(
        install_flashcli=True,
        quiet=quiet,
        force=force,
    )
    print("flashcli environment install complete.")
