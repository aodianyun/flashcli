"""Bundle inference entry — runs inside the bundle venv (not the host CLI)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import typer

from flashcli.models import cache as model_cache
from flashcli.models.registry import PresetRegistry
from flashcli.runtime.infer_helpers import (
    auto_install_flag,
    ensure_flashcli_serve_imports,
    retry_after_bundle_repair,
)

app = typer.Typer(
    name="flashcli-infer",
    help="Internal: run/serve inside bundle venv (invoked by flashcli re-exec).",
    no_args_is_help=True,
)


def execute_run(
    preset: str,
    *,
    bundle: Path | None = None,
    checkpoint: Path | None = None,
    mtp_checkpoint: Path | None = None,
    prompt: str | None = "pick up the red block and place it in the tray",
    max_tokens: int = 256,
    K: int | None = None,
    model: str | None = None,
    image: str | None = None,
    num_views: int | None = None,
    hardware: str | None = None,
    autotune: int | None = None,
    benchmark: int = 0,
    warmup: int = 0,
    no_auto_install: bool = False,
    quiet: bool = False,
) -> None:
    from flashcli.bundle.variants import resolve_effective_model_variant
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_run_engine

    p = PresetRegistry().get(preset)

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            auto_install_python=auto_install_flag(no_auto_install),
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

    auto_install = auto_install_flag(no_auto_install)
    try:
        run_engine = retry_after_bundle_repair(
            lambda: create_run_engine(
                p,
                bundle_path=bundle,
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


def execute_serve(
    preset: str,
    *,
    bundle: Path | None = None,
    port: int = 8000,
    host: str = "0.0.0.0",
    checkpoint: Path | None = None,
    mtp_checkpoint: Path | None = None,
    warmup: str | None = None,
    warmup_preset: str | None = None,
    max_seq: int | None = None,
    max_q_seq: int | None = None,
    K: int | None = None,
    default_max_tokens: int | None = None,
    max_output_tokens: int | None = None,
    model: str | None = None,
    model_name: str | None = None,
    no_auto_install: bool = False,
    quiet: bool = False,
) -> None:
    from flashcli.bundle.variants import resolve_effective_model_variant, variant_serve_cfg
    from flashcli.engines.factory import BundleNotReadyError, activate_for_preset, create_serve_engine

    p = PresetRegistry().get(preset)
    auto_install = auto_install_flag(no_auto_install)

    try:
        activate_for_preset(
            p,
            bundle_path=bundle,
            auto_install_python=auto_install,
            quiet=quiet,
        )
    except BundleNotReadyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(BundleNotReadyError.exit_code) from exc

    from flashcli.bundle.activate import active_bundle

    active = active_bundle()

    try:
        ensure_flashcli_serve_imports(auto_install=auto_install, quiet=quiet)
        from flashcli.serve.app import build_app
    except ImportError as exc:
        typer.echo(
            f"Cannot load flashcli HTTP serve stack: {exc} "
            "(reinstall host flashcli or run with bundle venv infer deps: typer, fastapi, uvicorn)",
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

    bundle_serve = (
        variant_serve_cfg(active, effective_variant)
        if active is not None
        else {}
    )

    try:
        ensure_flashcli_serve_imports(auto_install=auto_install, quiet=quiet)
        import uvicorn
    except ImportError as exc:
        typer.echo(f"Cannot load uvicorn: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        serve_engine = retry_after_bundle_repair(
            lambda: create_serve_engine(
                p,
                bundle_path=bundle,
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


@app.command("run")
def infer_run(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    checkpoint: Optional[Path] = typer.Option(None, "--checkpoint", exists=False),
    mtp_checkpoint: Optional[Path] = typer.Option(None, "--mtp-checkpoint"),
    prompt: Optional[str] = typer.Option(
        "pick up the red block and place it in the tray",
        "--prompt",
    ),
    max_tokens: int = typer.Option(256, "--max-tokens"),
    K: Optional[int] = typer.Option(None, "--K"),
    model: Optional[str] = typer.Option(None, "--model"),
    image: Optional[str] = typer.Option(None, "--image"),
    num_views: Optional[int] = typer.Option(None, "--num-views"),
    hardware: Optional[str] = typer.Option(None, "--hardware"),
    autotune: Optional[int] = typer.Option(None, "--autotune"),
    benchmark: int = typer.Option(0, "--benchmark"),
    warmup: int = typer.Option(0, "--warmup"),
    no_auto_install: bool = typer.Option(False, "--no-auto-install"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    execute_run(
        preset,
        bundle=bundle,
        checkpoint=checkpoint,
        mtp_checkpoint=mtp_checkpoint,
        prompt=prompt,
        max_tokens=max_tokens,
        K=K,
        model=model,
        image=image,
        num_views=num_views,
        hardware=hardware,
        autotune=autotune,
        benchmark=benchmark,
        warmup=warmup,
        no_auto_install=no_auto_install,
        quiet=quiet,
    )


@app.command("serve")
def infer_serve(
    preset: str = typer.Argument(..., help="Model preset name."),
    bundle: Optional[Path] = typer.Option(
        None,
        "--bundle",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    port: int = typer.Option(8000, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
    checkpoint: Optional[Path] = typer.Option(None, "--checkpoint"),
    mtp_checkpoint: Optional[Path] = typer.Option(None, "--mtp-checkpoint"),
    warmup: Optional[str] = typer.Option(None, "--warmup"),
    warmup_preset: Optional[str] = typer.Option(None, "--warmup-preset"),
    max_seq: Optional[int] = typer.Option(None, "--max-seq"),
    max_q_seq: Optional[int] = typer.Option(None, "--max-q-seq"),
    K: Optional[int] = typer.Option(None, "--K"),
    default_max_tokens: Optional[int] = typer.Option(None, "--default-max-tokens"),
    max_output_tokens: Optional[int] = typer.Option(None, "--max-output-tokens"),
    model: Optional[str] = typer.Option(None, "--model"),
    model_name: Optional[str] = typer.Option(None, "--model-name"),
    no_auto_install: bool = typer.Option(False, "--no-auto-install"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    execute_serve(
        preset,
        bundle=bundle,
        port=port,
        host=host,
        checkpoint=checkpoint,
        mtp_checkpoint=mtp_checkpoint,
        warmup=warmup,
        warmup_preset=warmup_preset,
        max_seq=max_seq,
        max_q_seq=max_q_seq,
        K=K,
        default_max_tokens=default_max_tokens,
        max_output_tokens=max_output_tokens,
        model=model,
        model_name=model_name,
        no_auto_install=no_auto_install,
        quiet=quiet,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
