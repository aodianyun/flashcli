"""Environment diagnostics and install."""

from __future__ import annotations

from flashcli import config
from flashcli.deps import flashcli_stack_satisfied
from flashcli.env import ensure_environment
from flashcli.runtime.detect import detect_gpu


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

    if flashcli_stack_satisfied():
        print("[ok] flashcli Python dependencies (typer, huggingface_hub, …)")
    else:
        print("[!] flashcli dependencies incomplete. Run: flashcli doctor --install")
        issues += 1

    from flashcli.bundle.activate import active_bundle
    from flashcli.deps import python_stack_satisfied

    b = active_bundle()
    if b is not None:
        print(f"[ok] Active model bundle: {b.bundle_root}")
        if python_stack_satisfied(bundle_root=b.bundle_root):
            print("[ok] Bundle runtime Python stack")
        else:
            print("[!] Bundle runtime Python stack incomplete.")
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
    ensure_environment(install_flashcli=True, quiet=quiet, force=force)
    print("Environment install complete.")
