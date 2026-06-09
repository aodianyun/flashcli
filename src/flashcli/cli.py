"""flashcli Typer entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from flashcli import __version__, config
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


def _version_callback(value: bool | None) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """FlashRT distribution CLI."""
    del version


def _auto_install_flag(no_auto_install: bool) -> bool:
    return not no_auto_install and not config.skip_auto_install()


def _bundle_torch_index(bundle) -> str:
    from flashcli.bundle.manifest import bundle_torch_index

    return bundle_torch_index(bundle)


def _retry_after_bundle_repair(
    action,
    *,
    bundle,
    auto_install: bool,
    quiet: bool,
):
    """Run *action*; on ImportError auto-install missing bundle deps and retry once."""
    try:
        return action()
    except ImportError:
        if not auto_install or bundle is None:
            raise
        from flashcli.deps import repair_bundle_python_stack
        from flashcli.runtime.bundle_venv import venv_python
        import os

        runtime_id = os.environ.get("FLASHCLI_RUNTIME_ID", "")
        py = venv_python(runtime_id) if runtime_id else None

        if not quiet:
            typer.echo("Missing bundle dependency; installing ...", err=True)
        repair_bundle_python_stack(
            bundle_root=bundle.bundle_root,
            torch_index=_bundle_torch_index(bundle),
            python=py,
            quiet=quiet,
        )
        return action()


def _ensure_flashcli_serve_imports(*, auto_install: bool, quiet: bool) -> None:
    """Verify flashcli HTTP stack (fastapi/uvicorn); auto-install on demand."""
    try:
        __import__("fastapi")
        __import__("uvicorn")
    except ImportError:
        if not auto_install:
            raise
        from flashcli.deps import repair_flashcli_serve_stack

        if not quiet:
            typer.echo("Installing flashcli serve dependencies ...", err=True)
        repair_flashcli_serve_stack(quiet=quiet)
        __import__("fastapi")
        __import__("uvicorn")


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
    from flashcli.bundle.marker import read_preset_marker
    from flashcli.runtime.detect import detect_gpu

    reg = PresetRegistry()
    gpu = detect_gpu()
    for name in reg.list_names():
        preset = reg.get(name)
        variant_tag = ""
        if preset.bundle_variant:
            variant_tag = f", variant={preset.bundle_variant}"
        weights = "weights:cached" if model_cache.is_cached(name) else "weights:missing"
        marker = read_preset_marker(name) or {}
        if marker.get("bundle_root"):
            bundle_state = f"bundle:cached ({marker.get('env_key', '?')})"
        else:
            bundle_state = "bundle:missing"
        typer.echo(f"{name}: {preset.description} [{bundle_state}{variant_tag}, {weights}]")


@models_app.command("envs")
def models_envs(
    preset: Optional[str] = typer.Argument(
        None, help="Preset name (omit to show all presets)."
    ),
) -> None:
    """List bundle runtime support and the current machine match."""
    from flashcli.bundle.catalog import raw_bundle_cfg, repo_url_for_preset
    from flashcli.bundle.flashhub import download_manifest_from_repo
    from flashcli.bundle.layout import is_bundle_root
    from flashcli.bundle.manifest import bundle_runtime_matrix, bundle_python_abi, load_bundle_manifest
    from flashcli.bundle.preflight import host_env_key
    from flashcli.runtime.detect import detect_gpu
    from flashcli import config

    reg = PresetRegistry()
    names = [preset] if preset else reg.list_names()
    gpu = detect_gpu()
    if gpu is None:
        typer.echo("[!] No NVIDIA GPU detected; cannot match an environment.")
    typer.echo("")
    for name in names:
        p = reg.get(name)
        typer.echo(f"{name}:")
        cfg = raw_bundle_cfg(p)
        src = "repo" if cfg.get("repo") else "path" if cfg.get("path") else "?"
        typer.echo(f"  catalog: bundle source ({src})")
        manifest = None
        path_str = str(cfg.get("path", "")).strip()
        if path_str:
            root = Path(path_str).expanduser()
            if not root.is_absolute():
                root = (config.package_root() / root).resolve()
            if is_bundle_root(root):
                try:
                    manifest = load_bundle_manifest(root)
                except Exception as exc:
                    typer.echo(f"  manifest: error — {exc}")
        elif cfg.get("repo"):
            try:
                import tempfile

                from flashcli.bundle.manifest import load_bundle_manifest_data

                tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{name}.json"
                data = download_manifest_from_repo(str(cfg["repo"]), tmp, quiet=True)
                manifest = load_bundle_manifest_data(data, bundle_root=Path("/tmp"))
            except Exception as exc:
                typer.echo(f"  manifest: error — {exc}")
        if manifest is not None and gpu is not None:
            try:
                abi = bundle_python_abi(manifest)
                env = host_env_key(gpu, abi)
                matrix = bundle_runtime_matrix(manifest)
                typer.echo(f"  this machine: {env} (python_abi={abi})")
                typer.echo(f"  supported ({len(matrix)}):")
                for key in matrix[:10]:
                    mark = " ← match" if key == env else ""
                    typer.echo(f"    - {key}{mark}")
                if len(matrix) > 10:
                    typer.echo(f"    ... +{len(matrix) - 10} more")
            except Exception as exc:
                typer.echo(f"  native envs: {exc}")
        if cfg.get("repo"):
            repo = str(cfg["repo"])
            label = repo if len(repo) <= 72 else repo[:69] + "..."
            typer.echo(f"  repo: {label}")
        typer.echo("")


@bundle_app.command("sync")
def bundle_sync(
    preset: str = typer.Argument(..., help="Model preset name from models.yaml."),
    force: bool = typer.Option(False, "--force", help="Re-download manifest and artifacts."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Fetch bundle runtime from FlashHub (manifest-first, split artifacts)."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.runtime.reexec import prepare_bundle_runtime

    p = PresetRegistry().get(preset)
    try:
        _runtime_id, bundle_root = prepare_bundle_runtime(
            p, quiet=quiet, force=force
        )
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Synced bundle for {preset!r} -> {bundle_root}")


@bundle_app.command("clean")
def bundle_clean(
    preset: Optional[str] = typer.Argument(
        None, help="Preset name (omit to clean all cached runtimes)."
    ),
    all_runtimes: bool = typer.Option(
        False, "--all", help="Remove all under ~/.flashcli/runtimes/."
    ),
) -> None:
    """Remove cached bundle runtimes and venvs."""
    import shutil

    from flashcli import config
    from flashcli.bundle.marker import read_preset_marker, runtime_dir

    if all_runtimes or preset is None:
        if config.RUNTIMES_DIR.is_dir():
            shutil.rmtree(config.RUNTIMES_DIR)
            typer.echo(f"Removed {config.RUNTIMES_DIR}")
        return

    marker = read_preset_marker(preset)
    if marker and marker.get("runtime_id"):
        rid = str(marker["runtime_id"])
        path = runtime_dir(rid)
        if path.is_dir():
            shutil.rmtree(path)
            typer.echo(f"Removed runtime {rid}")
            return
    typer.echo(f"No cached runtime for preset {preset!r}")


@bundle_app.command("validate")
def bundle_validate(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    skip_abi_probe: bool = typer.Option(
        False,
        "--skip-abi-probe",
        help="Skip loading each runtime/*.so with its tagged Python (faster; matrix only).",
    ),
) -> None:
    """Validate bundle layout, runtime/<env-key>/ completeness, and native ABI vs filenames."""
    from flashcli.bundle.manifest import (
        bundle_runtime_matrix,
        load_bundle_manifest,
        validate_bundle_layout,
    )

    bundle = load_bundle_manifest(path)
    errors = validate_bundle_layout(bundle, probe_abi=not skip_abi_probe)
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
    nm = bundle_runtime_matrix(bundle)
    if nm:
        detail = "ABI probed" if not skip_abi_probe else "matrix only"
        typer.echo(
            f"OK: bundle {bundle.name!r} at {bundle.bundle_root} "
            f"(runtime map: {len(nm)} env(s), {detail})"
        )
    else:
        typer.echo(f"OK: bundle {bundle.name!r} at {bundle.bundle_root}")


@bundle_app.command("install")
def bundle_install(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    force: bool = typer.Option(False, "--force"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Install bundle inference dependencies from flashcli-bundle.json (torch, transformers, …)."""
    from flashcli.bundle.activate import activate_bundle
    from flashcli.bundle.manifest import load_bundle_manifest

    bundle = load_bundle_manifest(path)
    activate_bundle(
        bundle,
        install_python=True,
        quiet=quiet,
        force_python=force,
    )
    typer.echo("Bundle inference dependencies installed.")


@app.command()
def pull(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Override bundle root (local dev tree).",
    ),
    no_auto_install: bool = typer.Option(
        False,
        "--no-auto-install",
        help="Do not auto-install Python stack.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Download model weights (and sync runtime bundle if needed)."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.runtime.reexec import prepare_bundle_runtime

    p = PresetRegistry().get(preset)
    try:
        prepare_bundle_runtime(p, bundle_path=bundle, quiet=quiet)
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)
    model_cache.ensure_model_cached(
        preset,
        bundle_path=bundle,
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
        help="Override bundle root (default: FlashHub repo from models.yaml).",
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
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Override catalog bundle_variant (e.g. qwen3, qwen36).",
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
    warmup: int = typer.Option(
        0,
        "--warmup",
        help="Extra predict iterations before --benchmark (not CUDA graph warmup; graph warmup runs on load).",
    ),
    no_auto_install: bool = typer.Option(
        False,
        "--no-auto-install",
        help="Do not auto-install bundle Python deps.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Run inference using the preset's model bundle."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.bundle.variants import resolve_effective_model_variant
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_run_engine
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

    p = PresetRegistry().get(preset)

    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)

    try:
        ensure_bundle_runtime_and_reexec(
            p, bundle_path=bundle, quiet=quiet
        )
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            auto_install_python=_auto_install_flag(no_auto_install),
            quiet=quiet,
        )
    except BundleNotReadyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(BundleNotReadyError.exit_code) from exc

    from flashcli.bundle.activate import active_bundle

    active = active_bundle()
    effective_variant = resolve_effective_model_variant(
        p, active, cli_override=model
    )

    try:
        ckpt = model_cache.ensure_model_cached(
            preset,
            bundle_path=bundle,
            checkpoint_override=checkpoint,
            mtp_checkpoint_override=mtp_checkpoint,
            model_variant=effective_variant,
            quiet=quiet,
        )
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    image_paths: list[Path] | None = None
    if image:
        image_paths = [Path(part.strip()) for part in image.split(",") if part.strip()]

    auto_install = _auto_install_flag(no_auto_install)
    try:
        run_engine = _retry_after_bundle_repair(
            lambda: create_run_engine(
                p,
                bundle_path=bundle,
                checkpoint=Path(ckpt),
            ),
            bundle=active,
            auto_install=auto_install,
            quiet=quiet,
        )
    except ImportError as exc:
        typer.echo(f"Cannot load run engine: {exc}", err=True)
        raise typer.Exit(1) from exc
    load_kw: dict = {
        "num_views": num_views,
        "hardware": hardware,
        "autotune": autotune,
    }
    if K is not None:
        load_kw["K"] = K
    if effective_variant:
        load_kw["model"] = effective_variant
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
        help="Override bundle root (default: FlashHub repo from models.yaml).",
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
        help='Extra graph warmup shapes, e.g. "32:128,128:256".',
    ),
    warmup_preset: Optional[str] = typer.Option(
        None,
        "--warmup-preset",
        help="Warmup bucket preset (bundle-specific; qwen3: auto|short|all|none; qwen36: agent|short|long|all|none).",
    ),
    max_seq: Optional[int] = typer.Option(
        None,
        "--max-seq",
        help="KV / context budget (qwen36 long ctx e.g. 262208).",
    ),
    max_q_seq: Optional[int] = typer.Option(
        None,
        "--max-q-seq",
        help="Max prefill chunk (qwen3 only, default from bundle).",
    ),
    K: Optional[int] = typer.Option(None, "--K", help="MTP speculative K (Qwen3.6)."),
    default_max_tokens: Optional[int] = typer.Option(
        None,
        "--default-max-tokens",
        help="Default max_tokens when the client omits it (qwen36 only, default 2048).",
    ),
    max_output_tokens: Optional[int] = typer.Option(
        None,
        "--max-output-tokens",
        help="Hard cap on generated tokens per request (qwen36 only, default 16384).",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Override catalog bundle_variant (e.g. qwen3, qwen36).",
    ),
    model_name: Optional[str] = typer.Option(None, "--model-name"),
    no_auto_install: bool = typer.Option(False, "--no-auto-install"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Serve unified OpenAI HTTP API via the preset model bundle."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.bundle.variants import resolve_effective_model_variant
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_serve_engine
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

    p = PresetRegistry().get(preset)

    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)

    try:
        ensure_bundle_runtime_and_reexec(
            p, bundle_path=bundle, quiet=quiet
        )
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            auto_install_python=_auto_install_flag(no_auto_install),
            quiet=quiet,
        )
    except BundleNotReadyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(BundleNotReadyError.exit_code) from exc

    from flashcli.bundle.activate import active_bundle

    active = active_bundle()
    auto_install = _auto_install_flag(no_auto_install)

    try:
        _ensure_flashcli_serve_imports(auto_install=auto_install, quiet=quiet)
        from flashcli.serve.app import build_app
    except ImportError as exc:
        typer.echo(
            f"Cannot load flashcli HTTP serve stack: {exc} "
            "(reinstall flashcli: pip install -e .)",
            err=True,
        )
        raise typer.Exit(1) from exc

    effective_variant = resolve_effective_model_variant(
        p, active, cli_override=model
    )

    try:
        ckpt = model_cache.ensure_model_cached(
            preset,
            bundle_path=bundle,
            checkpoint_override=checkpoint,
            mtp_checkpoint_override=mtp_checkpoint,
            model_variant=effective_variant,
            quiet=quiet,
        )
    except (NotImplementedError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    from flashcli.bundle.variants import variant_serve_cfg

    bundle_serve = (
        variant_serve_cfg(active, effective_variant)
        if active is not None
        else {}
    )

    try:
        _ensure_flashcli_serve_imports(auto_install=auto_install, quiet=quiet)
        import uvicorn
    except ImportError as exc:
        typer.echo(f"Cannot load uvicorn: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        serve_engine = _retry_after_bundle_repair(
            lambda: create_serve_engine(
                p,
                bundle_path=bundle,
                checkpoint=Path(ckpt),
            ),
            bundle=active,
            auto_install=auto_install,
            quiet=quiet,
        )
    except ImportError as exc:
        typer.echo(f"Cannot load serve engine: {exc}", err=True)
        raise typer.Exit(1) from exc
    opts: dict = {
        "model_name": model_name,
        "K": K,
        "model": effective_variant,
        "max_seq": max_seq,
        "max_q_seq": max_q_seq,
        "warmup_preset": warmup_preset,
        "default_max_tokens": default_max_tokens,
        "max_output_tokens": max_output_tokens,
    }
    opts = {k: v for k, v in opts.items() if v is not None}
    serve_engine.load(Path(ckpt), p, **opts)

    warm_spec: str | None = None
    if warmup_preset or warmup or bundle_serve.get("warmup"):
        if hasattr(serve_engine, "resolve_warmup"):
            warm_spec = serve_engine.resolve_warmup(
                preset=warmup_preset,
                extra_spec=warmup,
                bundle_default=str(bundle_serve.get("warmup", "")) or None
                if warmup is None and warmup_preset is None
                else None,
            )
        elif warmup:
            warm_spec = warmup
        elif bundle_serve.get("warmup"):
            warm_spec = str(bundle_serve.get("warmup"))
        elif warmup_preset:
            typer.echo(
                "This bundle does not support --warmup-preset; use --warmup instead.",
                err=True,
            )
            raise typer.Exit(1)
    if warm_spec:
        serve_engine.warmup(warm_spec)

    if not quiet:
        typer.echo(
            f"Serving {serve_engine.model_id} on http://{host}:{port} "
            f"(unified flashcli API; logs=INFO, /health stays responsive)"
        )

    import logging
    import os

    serve_log_level = os.environ.get("FLASHCLI_SERVE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, serve_log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    uvicorn_log = os.environ.get("FLASHCLI_UVICORN_LOG_LEVEL", "info").lower()

    try:
        uvicorn.run(
            build_app(serve_engine),
            host=host,
            port=port,
            log_level=uvicorn_log,
            access_log=True,
        )
    except Exception as exc:
        typer.echo(f"Serve failed: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
