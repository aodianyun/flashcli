"""Bundle inference entry — runs inside the bundle venv (not the host CLI)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

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
    model: str | None = None,
    benchmark: int = 0,
    warmup: int = 0,
    no_auto_install: bool = False,
    quiet: bool = False,
    bundle_options: dict[str, Any] | None = None,
    option_specs: list[Any] | None = None,
) -> None:
    from flashcli.bundle.bundle_options import (
        OptionSpec,
        bundle_run_options,
        split_run_options,
    )
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

    specs: list[OptionSpec] = list(option_specs or [])
    if not specs and active is not None:
        specs = bundle_run_options(active, variant=effective_variant)
    load_kw, predict_kw = split_run_options(bundle_options or {}, specs)

    image = predict_kw.pop("image", None)
    image_paths: list[Path] | None = None
    if image:
        image_paths = [
            Path(part.strip()) for part in str(image).split(",") if part.strip()
        ]

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

    if effective_variant:
        load_kw["model"] = effective_variant
    run_engine.load(
        Path(ckpt),
        p,
        **{k: v for k, v in load_kw.items() if v is not None},
    )
    prompt = str(predict_kw.pop("prompt", "") or "")
    try:
        actions = run_engine.predict(
            prompt=prompt,
            image_paths=image_paths,
            benchmark=benchmark,
            warmup_iters=warmup,
            echo=not quiet,
            **predict_kw,
        )
        if not quiet and actions is not None:
            if isinstance(actions, str):
                if not prompt.strip():
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
    model: str | None = None,
    no_auto_install: bool = False,
    quiet: bool = False,
    bundle_options: dict[str, Any] | None = None,
    option_specs: list[Any] | None = None,
) -> None:
    from flashcli.bundle.bundle_options import (
        OptionSpec,
        bundle_serve_options,
        serve_option_defaults,
        split_serve_options,
    )
    from flashcli.bundle.variants import resolve_effective_model_variant
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

    specs: list[OptionSpec] = list(option_specs or [])
    if not specs and active is not None:
        specs = bundle_serve_options(active, variant=effective_variant)
    load_kw, warmup_kw = split_serve_options(bundle_options or {}, specs)
    bundle_serve = (
        serve_option_defaults(active, variant=effective_variant)
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

    opts = dict(load_kw)
    if effective_variant:
        opts["model"] = effective_variant
    opts = {k: v for k, v in opts.items() if v is not None}
    serve_engine.load(Path(ckpt), p, **opts)

    warmup_preset = warmup_kw.get("warmup_preset")
    warmup = warmup_kw.get("warmup")
    if warmup_preset or warmup or bundle_serve.get("warmup"):
        warm_spec: str | None = None
        if hasattr(serve_engine, "resolve_warmup"):
            warm_spec = serve_engine.resolve_warmup(
                preset=str(warmup_preset) if warmup_preset is not None else None,
                extra_spec=str(warmup) if warmup is not None else None,
                bundle_default=str(bundle_serve.get("warmup", "")) or None
                if warmup is None and warmup_preset is None
                else None,
            )
        elif warmup:
            warm_spec = str(warmup)
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


@app.command(
    "run",
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def infer_run() -> None:
    import sys

    from flashcli.bundle.bundle_options import (
        BundleOptionsError,
        format_run_help,
        parse_run_argv,
        resolve_manifest_for_preset,
        resolve_preset_from_command_argv,
    )

    try:
        preset_name = resolve_preset_from_command_argv(sys.argv[1:], command="run")
        p = PresetRegistry().get(preset_name)
        inv = parse_run_argv(sys.argv[1:], preset=p)
    except BundleOptionsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if inv.help:
        try:
            manifest = resolve_manifest_for_preset(p, bundle_path=inv.bundle)
            specs = inv.option_specs or []
            typer.echo(format_run_help(p, manifest, specs))
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        raise typer.Exit()

    execute_run(
        preset_name,
        bundle=inv.bundle,
        checkpoint=inv.checkpoint,
        mtp_checkpoint=inv.mtp_checkpoint,
        model=inv.model,
        benchmark=inv.benchmark,
        warmup=inv.warmup,
        no_auto_install=inv.no_auto_install,
        quiet=inv.quiet,
        bundle_options=inv.bundle_options,
        option_specs=inv.option_specs,
    )


@app.command(
    "serve",
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def infer_serve() -> None:
    import sys

    from flashcli.bundle.bundle_options import (
        BundleOptionsError,
        format_serve_help,
        parse_serve_argv,
        resolve_manifest_for_preset,
        resolve_preset_from_command_argv,
    )

    try:
        preset_name = resolve_preset_from_command_argv(sys.argv[1:], command="serve")
        p = PresetRegistry().get(preset_name)
        inv = parse_serve_argv(sys.argv[1:], preset=p)
    except BundleOptionsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if inv.help:
        try:
            manifest = resolve_manifest_for_preset(p, bundle_path=inv.bundle)
            specs = inv.option_specs or []
            typer.echo(format_serve_help(p, manifest, specs))
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        raise typer.Exit()

    execute_serve(
        preset_name,
        bundle=inv.bundle,
        port=inv.port,
        host=inv.host,
        checkpoint=inv.checkpoint,
        mtp_checkpoint=inv.mtp_checkpoint,
        model=inv.model,
        no_auto_install=inv.no_auto_install,
        quiet=inv.quiet,
        bundle_options=inv.bundle_options,
        option_specs=inv.option_specs,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
