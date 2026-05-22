"""flashcli Typer entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from flashcli import config
from flashcli.doctor import run_check, run_install
from flashcli.env import ensure_environment
from flashcli.models import cache as model_cache
from flashcli.models.registry import PresetRegistry

app = typer.Typer(
    name="flashcli",
    help="FlashRT distribution CLI — model bundles, inference, serve.",
    no_args_is_help=True,
)
doctor_app = typer.Typer(help="Diagnose and install environment.")
models_app = typer.Typer(help="Model presets and cache.")
bundle_app = typer.Typer(help="Model bundle utilities.")
app.add_typer(doctor_app, name="doctor")
app.add_typer(models_app, name="models")
app.add_typer(bundle_app, name="bundle")


def _auto_install_flag(no_auto_install: bool) -> bool:
    return not no_auto_install and not config.skip_auto_install()


@doctor_app.callback(invoke_without_command=True)
def doctor_main(
    ctx: typer.Context,
    install: bool = typer.Option(
        False,
        "--install",
        help="Install flashcli CLI dependencies (typer, huggingface_hub, …).",
    ),
    force: bool = typer.Option(False, "--force", help="Reinstall even if satisfied."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Check or install environment."""
    if ctx.invoked_subcommand is not None:
        return
    if install:
        run_install(quiet=quiet, force=force)
        raise typer.Exit(0)
    code = run_check(quiet=quiet)
    raise typer.Exit(code)


@models_app.command("list")
def models_list() -> None:
    from flashcli.bundle.git import read_bundle_marker
    from flashcli.bundle.ref import resolve_requested_git_ref
    from flashcli.bundle.zip import is_preset_bundle_cached, zip_spec
    from flashcli.runtime.detect import detect_gpu

    reg = PresetRegistry()
    gpu = detect_gpu()
    for name in reg.list_names():
        preset = reg.get(name)
        weights = "weights:cached" if model_cache.is_cached(name) else "weights:missing"
        try:
            has_zip = zip_spec(preset) is not None
        except Exception as exc:
            bundle_state = f"bundle:error ({exc})"
            typer.echo(f"{name}: {preset.description} [{bundle_state}, {weights}]")
            continue
        if is_preset_bundle_cached(preset):
            marker = read_bundle_marker(name) or {}
            variant = marker.get("variant", "?")
            if has_zip:
                bundle_state = f"bundle:cached ({variant}, zip)"
            else:
                want_ref = resolve_requested_git_ref(preset)
                ref = marker.get("git_ref") or marker.get("version", want_ref)
                bundle_state = f"bundle:cached ({variant} @{ref})"
        elif has_zip:
            bundle_state = "bundle:missing (want zip)"
        else:
            want_ref = resolve_requested_git_ref(preset)
            bundle_state = f"bundle:missing (want @{want_ref})"
        typer.echo(f"{name}: {preset.description} [{bundle_state}, {weights}]")


@models_app.command("envs")
def models_envs(
    preset: Optional[str] = typer.Argument(
        None, help="Preset name (omit to show all presets)."
    ),
) -> None:
    """List bundle environments in models.yaml and the current machine match."""
    from flashcli.bundle.catalog import resolve_effective_bundle_cfg, variant_dir_name
    from flashcli.bundle.manifest import load_bundle_manifest
    from flashcli.bundle.native_naming import list_native_artifacts
    from flashcli.bundle.resolve import _local_bundle_ready
    from flashcli.bundle.runtime_env import host_python_minor
    from flashcli.bundle.zip import zip_spec
    from flashcli.runtime.detect import detect_gpu

    reg = PresetRegistry()
    names = [preset] if preset else reg.list_names()
    gpu = detect_gpu()
    if gpu is None:
        typer.echo("[!] No NVIDIA GPU detected; cannot match an environment.")
    else:
        typer.echo(
            f"[i] This machine: {variant_dir_name(gpu)} "
            f"({gpu.gpu_name or 'GPU'}, sm{gpu.sm}, cuda_tag={gpu.cuda_tag}, "
            f"python={host_python_minor()})"
        )
    typer.echo("")
    for name in names:
        p = reg.get(name)
        typer.echo(f"{name}:")
        try:
            cfg, runtime_env = resolve_effective_bundle_cfg(
                p, gpu=gpu, require_gpu=False
            )
        except Exception as exc:
            typer.echo(f"  catalog: error — {exc}")
            continue
        src = "zip" if cfg.get("zip") else "path" if cfg.get("path") else "git"
        typer.echo(f"  catalog: single bundle ({src})")
        if gpu is not None:
            typer.echo(f"  runtime env: {runtime_env}")
        path_str = str(cfg.get("path", "")).strip()
        if path_str:
            from pathlib import Path

            root = Path(path_str).expanduser()
            if not root.is_absolute():
                root = (config.package_root().parent / root).resolve()
            if _local_bundle_ready(root):
                try:
                    manifest = load_bundle_manifest(root)
                    matrix = manifest.raw.get("native_matrix")
                    if isinstance(matrix, list) and matrix:
                        typer.echo(f"  lib/: {len(matrix)} native env(s) in bundle")
                        for key in matrix[:8]:
                            typer.echo(f"    - {key}")
                        if len(matrix) > 8:
                            typer.echo(f"    ... +{len(matrix) - 8} more")
                    elif (root / "lib").is_dir():
                        arts = list_native_artifacts(root / "lib")
                        keys = sorted(
                            {
                                parsed.catalog_key()
                                for items in arts.values()
                                for parsed, _ in items
                            }
                        )
                        if keys:
                            typer.echo(f"  lib/: {len(keys)} native env(s)")
                            for key in keys[:8]:
                                typer.echo(f"    - {key}")
                except Exception as exc:
                    typer.echo(f"  lib/: (unreadable) {exc}")
        if gpu is not None and cfg.get("zip"):
            try:
                spec = zip_spec(p)
                if spec:
                    label = spec if len(spec) <= 60 else spec[:57] + "..."
                    typer.echo(f"  zip: {label}")
            except Exception:
                pass


@models_app.command("refs")
def models_refs(
    preset: str = typer.Argument(..., help="Model preset name."),
) -> None:
    """List declared and locally cached git refs for a preset's runtime bundle."""
    from flashcli.bundle.git import (
        list_bundle_refs_for_preset,
        list_cached_refs,
        read_bundle_marker,
    )
    from flashcli.bundle.ref import resolve_requested_git_ref

    p = PresetRegistry().get(preset)
    typer.echo(f"{preset}: default ref {resolve_requested_git_ref(p)!r}")
    catalog = list_bundle_refs_for_preset(p)
    if catalog:
        typer.echo("  catalog (models.yaml bundle.refs):")
        for ref in catalog:
            typer.echo(f"    - {ref}")
    marker = read_bundle_marker(preset)
    if marker:
        active = marker.get("git_ref") or marker.get("version", "?")
        typer.echo(
            f"  active: @{active} -> {marker.get('bundle_root', '')}"
        )
    cached = list_cached_refs(preset)
    if cached:
        typer.echo(f"  local clones: {', '.join(cached)}")


@models_app.command("versions")
def models_versions(
    preset: str = typer.Argument(..., help="Model preset name."),
) -> None:
    """Alias for ``flashcli models refs`` (legacy command name)."""
    models_refs(preset)


@bundle_app.command("validate")
def bundle_validate(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
) -> None:
    """Validate a model bundle directory layout."""
    from flashcli.bundle.manifest import load_bundle_manifest, validate_bundle_layout

    bundle = load_bundle_manifest(path)
    errors = validate_bundle_layout(bundle)
    if errors:
        for err in errors:
            typer.echo(f"ERROR: {err}", err=True)
        raise typer.Exit(1)
    from flashcli.bundle.native import verify_native_modules

    try:
        from flashcli.runtime.detect import detect_gpu

        _gpu = detect_gpu()
        verify_native_modules(bundle, gpu=_gpu)
    except RuntimeError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"OK: bundle {bundle.name!r} at {bundle.bundle_root}")


@bundle_app.command("install")
def bundle_install(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    profile: str = typer.Option("default", "--profile", help="default | serve"),
    force: bool = typer.Option(False, "--force"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Install Python dependencies from flashcli-bundle.json."""
    from flashcli.bundle.activate import activate_bundle
    from flashcli.bundle.manifest import load_bundle_manifest

    if profile not in ("default", "serve"):
        typer.echo("profile must be 'default' or 'serve'", err=True)
        raise typer.Exit(1)
    bundle = load_bundle_manifest(path)
    activate_bundle(
        bundle,
        profile=profile,  # type: ignore[arg-type]
        install_python=True,
        quiet=quiet,
        force_python=force,
    )
    typer.echo("Bundle dependencies installed.")


@bundle_app.command("sync")
def bundle_sync(
    preset: str = typer.Argument(..., help="Model preset name from models.yaml."),
    bundle_ref: Optional[str] = typer.Option(
        None,
        "--bundle-ref",
        "--bundle-version",
        help="Git ref for runtime bundle (default: models.yaml bundle.git.ref).",
    ),
    force: bool = typer.Option(False, "--force", help="Re-fetch git repo and re-select variant."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Fetch or update the model runtime bundle (git or zip per models.yaml)."""
    from flashcli.bundle.git import ensure_bundle_from_git
    from flashcli.bundle.zip import ensure_bundle_from_zip, zip_spec

    p = PresetRegistry().get(preset)
    if zip_spec(p):
        if bundle_ref:
            typer.echo(
                "Note: --bundle-ref is ignored for zip bundles.",
                err=True,
            )
        root = ensure_bundle_from_zip(p, force=force, quiet=quiet)
    else:
        root = ensure_bundle_from_git(
            p, bundle_ref=bundle_ref, force=force, quiet=quiet
        )
    typer.echo(f"Synced bundle for {preset!r} -> {root}")


@app.command()
def pull(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Override bundle root (default: git fetch per models.yaml).",
    ),
    bundle_ref: Optional[str] = typer.Option(
        None,
        "--bundle-ref",
        "--bundle-version",
        help="Git ref for runtime bundle (default: models.yaml bundle.git.ref).",
    ),
    no_auto_install: bool = typer.Option(
        False,
        "--no-auto-install",
        help="Do not auto-install Python stack.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Download model weights (and sync runtime bundle if needed)."""
    from flashcli.bundle.resolve import resolve_bundle_root

    p = PresetRegistry().get(preset)
    if bundle is None:
        resolve_bundle_root(p, bundle_ref=bundle_ref, quiet=quiet)
    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)
    model_cache.ensure_model_cached(
        preset,
        bundle_path=bundle,
        bundle_ref=bundle_ref,
        quiet=quiet,
    )


@app.command()
def run(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Override bundle root (default: auto from models.yaml git catalog).",
    ),
    bundle_ref: Optional[str] = typer.Option(
        None,
        "--bundle-ref",
        "--bundle-version",
        help="Git ref for runtime bundle (default: models.yaml bundle.git.ref).",
    ),
    checkpoint: Optional[Path] = typer.Option(
        None,
        "--checkpoint",
        exists=False,
        help="Override checkpoint directory (skip cache/download).",
    ),
    mtp_checkpoint: Optional[Path] = typer.Option(
        None,
        "--mtp-checkpoint",
        help="Override MTP weights dir (Qwen3.6; sets FLASHRT_QWEN36_MTP_CKPT_DIR).",
    ),
    prompt: Optional[str] = typer.Option(
        "pick up the red block and place it in the tray",
        "--prompt",
        help="Task / chat user prompt.",
    ),
    max_tokens: int = typer.Option(
        256,
        "--max-tokens",
        help="Max new tokens for LLM presets (Qwen).",
    ),
    K: Optional[int] = typer.Option(
        None,
        "--K",
        help="MTP speculative K for Qwen3.6 run.",
    ),
    image: Optional[str] = typer.Option(
        None, "--image", help="Comma-separated image paths (one per view)."
    ),
    num_views: Optional[int] = typer.Option(
        None, "--num-views", help="Override preset default camera views."
    ),
    hardware: Optional[str] = typer.Option(
        None,
        "--hardware",
        help="Backend: auto, rtx_sm89, rtx_sm120, thor.",
    ),
    autotune: Optional[int] = typer.Option(
        None, "--autotune", help="CUDA graph autotune trials (0=off, 3=default)."
    ),
    benchmark: int = typer.Option(0, "--benchmark", help="Timed iterations after first predict."),
    warmup: int = typer.Option(20, "--warmup", help="Warmup iterations before --benchmark."),
    no_auto_install: bool = typer.Option(
        False,
        "--no-auto-install",
        help="Do not auto-install bundle Python deps.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Run inference using the preset's model bundle."""
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_run_engine

    p = PresetRegistry().get(preset)

    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            bundle_ref=bundle_ref,
            profile="default",
            auto_install_python=_auto_install_flag(no_auto_install),
            quiet=quiet,
        )
    except BundleNotReadyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(BundleNotReadyError.exit_code) from exc

    try:
        ckpt = model_cache.ensure_model_cached(
            preset,
            bundle_path=bundle,
            bundle_ref=bundle_ref,
            checkpoint_override=checkpoint,
            mtp_checkpoint_override=mtp_checkpoint,
            quiet=quiet,
        )
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    image_paths: list[Path] | None = None
    if image:
        image_paths = [Path(part.strip()) for part in image.split(",") if part.strip()]

    run_engine = create_run_engine(
        p,
        bundle_path=bundle,
        bundle_ref=bundle_ref,
        checkpoint=Path(ckpt),
    )
    load_kw: dict = {
        "num_views": num_views,
        "hardware": hardware,
        "autotune": autotune,
    }
    if K is not None:
        load_kw["K"] = K
    run_engine.load(Path(ckpt), p, **{k: v for k, v in load_kw.items() if v is not None})
    try:
        actions = run_engine.predict(
            prompt=prompt or "",
            image_paths=image_paths,
            benchmark=benchmark,
            warmup_iters=warmup,
            max_tokens=max_tokens,
            echo=not quiet,
        )
        if not quiet and actions is not None:
            if isinstance(actions, str):
                if not (prompt or "").strip():
                    typer.echo(actions)
            elif isinstance(actions, dict) and actions.get("text") is not None:
                pass
            else:
                typer.echo(f"Done. result type={type(actions).__name__}")
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except Exception as exc:
        typer.echo(f"Inference failed: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def serve(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Override bundle root (default: auto from models.yaml git catalog).",
    ),
    bundle_ref: Optional[str] = typer.Option(
        None,
        "--bundle-ref",
        "--bundle-version",
        help="Git ref for runtime bundle (default: models.yaml bundle.git.ref).",
    ),
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
    checkpoint: Optional[Path] = typer.Option(
        None,
        "--checkpoint",
        help="Override checkpoint directory.",
    ),
    mtp_checkpoint: Optional[Path] = typer.Option(
        None,
        "--mtp-checkpoint",
        help="Override MTP weights dir (sets env vars from preset).",
    ),
    warmup: Optional[str] = typer.Option(
        None,
        "--warmup",
        help='Graph warmup shapes, e.g. "8:512".',
    ),
    K: Optional[int] = typer.Option(None, "--K", help="MTP speculative K (Qwen3.6)."),
    model_name: Optional[str] = typer.Option(None, "--model-name"),
    no_auto_install: bool = typer.Option(False, "--no-auto-install"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Serve unified OpenAI HTTP API via the preset model bundle."""
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_serve_engine
    from flashcli.serve.app import build_app

    p = PresetRegistry().get(preset)

    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            bundle_ref=bundle_ref,
            profile="serve",
            auto_install_python=_auto_install_flag(no_auto_install),
            quiet=quiet,
        )
    except BundleNotReadyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(BundleNotReadyError.exit_code) from exc

    try:
        ckpt = model_cache.ensure_model_cached(
            preset,
            bundle_path=bundle,
            bundle_ref=bundle_ref,
            checkpoint_override=checkpoint,
            mtp_checkpoint_override=mtp_checkpoint,
            quiet=quiet,
        )
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    serve_cfg = p.raw.get("serve") or {}
    warm_spec = warmup
    if warm_spec is None and isinstance(serve_cfg, dict):
        warm_spec = str(serve_cfg.get("warmup", "")) or None

    try:
        import uvicorn
    except ImportError as exc:
        typer.echo(
            "uvicorn required for serve; run: flashcli bundle install <bundle> --profile serve",
            err=True,
        )
        raise typer.Exit(1) from exc

    serve_engine = create_serve_engine(
        p,
        bundle_path=bundle,
        bundle_ref=bundle_ref,
        checkpoint=Path(ckpt),
    )
    opts: dict = {"model_name": model_name, "K": K, "warmup": warm_spec}
    opts = {k: v for k, v in opts.items() if v is not None}
    serve_engine.load(Path(ckpt), p, **opts)
    if warm_spec:
        serve_engine.warmup(warm_spec)

    if not quiet:
        typer.echo(
            f"Serving {serve_engine.model_id} on http://{host}:{port} "
            f"(unified flashcli API)"
        )

    try:
        uvicorn.run(
            build_app(serve_engine),
            host=host,
            port=port,
            log_level="warning",
        )
    except Exception as exc:
        typer.echo(f"Serve failed: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
