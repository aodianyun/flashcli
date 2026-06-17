"""flashcli Typer entrypoint."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Callable, Optional, TypeVar

import typer

from flashcli import __version__, config
from flashcli.cli_errors import handle_cli_error
from flashcli.doctor import run_check, run_install
from flashcli.env import ensure_environment
from flashcli.models import cache as model_cache
from flashcli.models.registry import Preset

_F = TypeVar("_F", bound=Callable[..., None])

app = typer.Typer(
    name="flashcli",
    help="FlashRT distribution CLI — model bundles, inference, serve.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
doctor_app = typer.Typer(help="Diagnose and install environment.", pretty_exceptions_enable=False)
models_app = typer.Typer(help="Model presets and cache.", pretty_exceptions_enable=False)
bundle_app = typer.Typer(help="Model bundle utilities.", pretty_exceptions_enable=False)
app.add_typer(doctor_app, name="doctor")
app.add_typer(models_app, name="models")
app.add_typer(bundle_app, name="bundle")

_REF_HELP = "FlashHub ref or local bundle path PATH[@variant]"


def cli_command(fn: _F) -> _F:
    """Print concise errors for expected failures; propagate unexpected ones."""

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> None:
        try:
            fn(*args, **kwargs)
        except typer.Exit:
            raise
        except KeyboardInterrupt:
            raise typer.Exit(130) from None
        except Exception as exc:
            handle_cli_error(exc)

    return wrapper  # type: ignore[return-value]


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


def _resolve_ref_arg(ref: str) -> tuple[Preset, Path | None]:
    from flashcli.models.preset_ref import resolve_run_target

    return resolve_run_target(ref)


def _ensure_host_weights_before_reexec(
    preset: Preset,
    *,
    bundle: Path | None,
    checkpoint: Path | None,
    mtp_checkpoint: Path | None,
    quiet: bool,
) -> None:
    """Validate manifest, sync runtime, then pull weights on the host CLI."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.bundle.preset_validate import validate_preset_before_sync
    from flashcli.bundle.variants import resolve_effective_model_variant
    from flashcli.runtime.reexec import prepare_bundle_runtime

    try:
        manifest = validate_preset_before_sync(
            preset, bundle_path=bundle, quiet=quiet
        )
    except BundleEnvironmentError:
        raise

    try:
        prepare_bundle_runtime(preset, bundle_path=bundle, quiet=quiet)
    except BundleEnvironmentError:
        raise

    model_variant = resolve_effective_model_variant(preset, manifest)

    try:
        model_cache.ensure_model_cached(
            preset,
            bundle_path=bundle,
            checkpoint_override=checkpoint,
            mtp_checkpoint_override=mtp_checkpoint,
            model_variant=model_variant,
            quiet=quiet,
            download=True,
        )
    except FileNotFoundError:
        raise


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
    from flashcli.bundle.marker import list_cached_presets
    from flashcli.models.preset_ref import resolve_preset

    entries = list_cached_presets()
    if not entries:
        typer.echo("No cached presets. Run flashcli run <ref> or flashcli bundle sync <ref>.")
        return
    for entry in entries:
        ref = str(entry.get("ref", "")).strip()
        if not ref:
            continue
        try:
            preset = resolve_preset(ref)
        except ValueError:
            preset = None
        variant_tag = ""
        if preset and preset.bundle_variant:
            variant_tag = f", variant={preset.bundle_variant}"
        weights = (
            "weights:cached"
            if preset is not None and model_cache.is_cached(preset)
            else "weights:missing"
        )
        if entry.get("bundle_root"):
            bundle_state = f"bundle:cached ({entry.get('env_key', '?')})"
        else:
            bundle_state = "bundle:missing"
        typer.echo(f"{ref} [{bundle_state}{variant_tag}, {weights}]")


@models_app.command("show")
@cli_command
def models_show(
    preset: str = typer.Argument(..., help=_REF_HELP),
) -> None:
    """Show preset ref, cached runtime, and install paths (debugging)."""
    import sys

    from flashcli.bundle.catalog import raw_bundle_cfg
    from flashcli.bundle.marker import read_preset_marker, read_runtime_marker
    from flashcli.bundle.runtime_id import runtime_id_from_repo

    p, bundle_path = _resolve_ref_arg(preset)
    cfg = raw_bundle_cfg(p)

    typer.echo(f"flashcli: {__version__} ({sys.executable})")
    typer.echo(f"FlashHub API: {config.FLASHHUB_API_BASE}")
    typer.echo(f"ref: {p.name}")
    if bundle_path is not None:
        typer.echo(f"local_root: {bundle_path}")
    if p.bundle_variant:
        typer.echo(f"variant: {p.bundle_variant}")

    repo = str(cfg.get("repo", "")).strip()
    if repo:
        typer.echo(f"repo: {repo}")
        typer.echo(f"expected runtime_id: {runtime_id_from_repo(repo, p.name)}")

    marker = read_preset_marker(p) or {}
    if marker:
        typer.echo("cached preset marker:")
        for key in ("ref", "repo", "runtime_id", "bundle_root", "env_key", "source", "local_root"):
            val = marker.get(key)
            if val:
                typer.echo(f"  {key}: {val}")
        cached_repo = str(marker.get("repo", "")).strip()
        if repo and cached_repo and cached_repo != repo:
            typer.echo(
                f"  [!] cached repo differs from ref — "
                f"run: flashcli bundle sync {p.name} --force"
            )
        rid = str(marker.get("runtime_id", "")).strip()
        if rid:
            runtime_marker = read_runtime_marker(rid) or {}
            if runtime_marker.get("manifest_sha256"):
                typer.echo(f"  manifest_sha256: {runtime_marker['manifest_sha256']}")
    else:
        typer.echo("cached preset marker: (none — run flashcli run/serve or bundle sync)")

    typer.echo(f"weights: {'cached' if model_cache.is_cached(p) else 'missing'}")


@models_app.command("envs")
def models_envs(
    preset: Optional[str] = typer.Argument(
        None, help=f"Preset ref (omit to show all cached). {_REF_HELP}"
    ),
) -> None:
    """List bundle runtime support and the current machine match."""
    from flashcli.bundle.catalog import raw_bundle_cfg
    from flashcli.bundle.flashhub import download_manifest_from_repo
    from flashcli.bundle.manifest import (
        bundle_python_abi,
        bundle_runtime_matrix,
        load_bundle_manifest,
        load_bundle_manifest_data,
    )
    from flashcli.bundle.marker import list_cached_presets, read_preset_marker
    from flashcli.bundle.preflight import host_env_key
    from flashcli.bundle.python_install import ensure_python_for_minor
    from flashcli.models.preset_ref import resolve_run_target
    from flashcli.runtime.detect import detect_gpu
    import sys as _sys
    import tempfile

    gpu = detect_gpu()
    if gpu is None:
        typer.echo("[!] No NVIDIA GPU detected; cannot match an environment.")
    typer.echo(f"FlashHub API: {config.FLASHHUB_API_BASE}")
    typer.echo("")

    if preset:
        refs = [preset]
    else:
        refs = [
            str(e.get("ref", "")).strip()
            for e in list_cached_presets()
            if str(e.get("ref", "")).strip()
        ]
        if not refs:
            typer.echo("No cached presets. Pass a ref or run flashcli bundle sync <ref> first.")
            return

    for ref in refs:
        try:
            p, bundle_path = resolve_run_target(ref)
        except ValueError as exc:
            typer.echo(f"{ref}: invalid ref — {exc}")
            continue
        typer.echo(f"{ref}:")
        cfg = raw_bundle_cfg(p)
        manifest = None
        if bundle_path is not None:
            try:
                manifest = load_bundle_manifest(bundle_path)
            except (FileNotFoundError, ValueError) as exc:
                typer.echo(f"  manifest: error — {exc}")
        elif cfg.get("repo"):
            try:
                key = p.cache_key or "tmp"
                tmp = Path(tempfile.gettempdir()) / f"flashcli-manifest-{key}.json"
                data = download_manifest_from_repo(str(cfg["repo"]), tmp, quiet=True)
                manifest = load_bundle_manifest_data(data, bundle_root=Path("/tmp"))
            except Exception as exc:
                typer.echo(f"  manifest: error — {exc}")
        if manifest is not None and gpu is not None:
            try:
                abi = bundle_python_abi(manifest)
                env = host_env_key(gpu, abi)
                matrix = bundle_runtime_matrix(manifest)
                py_bin = ensure_python_for_minor(abi, auto_install=False)
                host_py = f"{_sys.version_info.major}.{_sys.version_info.minor}"
                typer.echo(f"  this machine: {env} (python_abi={abi})")
                if py_bin is not None:
                    typer.echo(f"  python 3.{abi[1:]}: {py_bin}")
                else:
                    typer.echo(
                        f"  python 3.{abi[1:]}: NOT FOUND "
                        f"(host CLI is {host_py}; will auto-install on run, or set "
                        f"FLASHCLI_PY{abi}_BIN / FLASHCLI_AUTO_INSTALL_BUNDLE_PYTHON=0)"
                    )
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
            typer.echo(f"  repo: {repo}")
            marker = read_preset_marker(p) or {}
            cached_repo = str(marker.get("repo", "")).strip()
            if cached_repo:
                typer.echo(f"  cached repo: {cached_repo}")
                if cached_repo != repo:
                    typer.echo(
                        f"  [!] cached repo changed — run: flashcli bundle sync {ref} --force"
                    )
            if marker.get("runtime_id"):
                typer.echo(f"  cached runtime_id: {marker['runtime_id']}")
        typer.echo("")


@bundle_app.command("sync")
@cli_command
def bundle_sync(
    preset: str = typer.Argument(..., help=_REF_HELP),
    force: bool = typer.Option(False, "--force", help="Re-download manifest and artifacts."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Fetch bundle runtime from FlashHub (manifest-first, split artifacts)."""
    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.runtime.reexec import prepare_bundle_runtime

    p, bundle_path = _resolve_ref_arg(preset)
    if bundle_path is not None:
        typer.echo(
            f"Local bundle {bundle_path} — runtime already on disk; "
            "bundle sync applies to FlashHub refs only.",
            err=True,
        )
        raise typer.Exit(1)
    try:
        _runtime_id, bundle_root = prepare_bundle_runtime(
            p, quiet=quiet, force=force
        )
    except BundleEnvironmentError:
        raise
    typer.echo(f"Synced bundle for {preset!r} -> {bundle_root}")


@bundle_app.command("clean")
def bundle_clean(
    preset: Optional[str] = typer.Argument(
        None, help=f"Preset ref (omit to clean all cached runtimes). {_REF_HELP}"
    ),
    all_runtimes: bool = typer.Option(
        False, "--all", help="Remove all under ~/.flashcli/runtimes/."
    ),
) -> None:
    """Remove cached bundle runtimes and venvs."""
    import shutil

    from flashcli.bundle.marker import read_preset_marker, runtime_dir

    if all_runtimes or preset is None:
        if config.RUNTIMES_DIR.is_dir():
            shutil.rmtree(config.RUNTIMES_DIR)
            typer.echo(f"Removed {config.RUNTIMES_DIR}")
        return

    p, _bundle_path = _resolve_ref_arg(preset)
    marker = read_preset_marker(p)
    if marker and marker.get("runtime_id"):
        rid = str(marker["runtime_id"])
        path = runtime_dir(rid)
        if path.is_dir():
            shutil.rmtree(path)
            typer.echo(f"Removed runtime {rid}")
            return
    typer.echo(f"No cached runtime for preset {preset!r}")


@bundle_app.command("validate")
@cli_command
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
    except RuntimeError:
        raise
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
@cli_command
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
@cli_command
def pull(
    ref: str = typer.Argument(..., help=_REF_HELP),
    no_auto_install: bool = typer.Option(
        False,
        "--no-auto-install",
        help="Do not auto-install Python stack.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Download model weights (and sync runtime bundle if needed)."""
    from flashcli.bundle.preset_validate import validate_preset_before_sync
    from flashcli.bundle.variants import resolve_effective_model_variant
    from flashcli.models.preset_ref import resolve_run_target
    from flashcli.runtime.reexec import prepare_bundle_runtime

    p, bundle_path = resolve_run_target(ref)

    manifest = validate_preset_before_sync(
        p, bundle_path=bundle_path, quiet=quiet
    )
    prepare_bundle_runtime(p, bundle_path=bundle_path, quiet=quiet)
    if _auto_install_flag(no_auto_install):
        ensure_environment(install_flashcli=True, quiet=quiet)
    model_variant = resolve_effective_model_variant(p, manifest)
    model_cache.ensure_model_cached(
        p,
        bundle_path=bundle_path,
        model_variant=model_variant,
        quiet=quiet,
    )


@app.command(
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@cli_command
def run() -> None:
    """Run inference using the preset's model bundle."""
    import sys

    from flashcli.bundle.run_argv import peel_host_run_flags, resolve_run_from_argv
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

    flags = peel_host_run_flags(sys.argv[1:], command="run")
    p, default_bundle = resolve_run_from_argv(sys.argv[1:], command="run")

    if _auto_install_flag(flags.no_auto_install):
        ensure_environment(install_flashcli=True, quiet=flags.quiet)

    if not flags.wants_help:
        _ensure_host_weights_before_reexec(
            p,
            bundle=default_bundle,
            checkpoint=flags.checkpoint,
            mtp_checkpoint=flags.mtp_checkpoint,
            quiet=flags.quiet,
        )
    ensure_bundle_runtime_and_reexec(
        p, bundle_path=default_bundle, quiet=flags.quiet
    )


@app.command(
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@cli_command
def serve() -> None:
    """Serve unified OpenAI HTTP API via the preset model bundle."""
    import sys

    from flashcli.bundle.run_argv import peel_host_run_flags, resolve_run_from_argv
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

    flags = peel_host_run_flags(sys.argv[1:], command="serve")
    p, default_bundle = resolve_run_from_argv(sys.argv[1:], command="serve")

    if _auto_install_flag(flags.no_auto_install):
        ensure_environment(install_flashcli=True, quiet=flags.quiet)

    if not flags.wants_help:
        _ensure_host_weights_before_reexec(
            p,
            bundle=default_bundle,
            checkpoint=flags.checkpoint,
            mtp_checkpoint=flags.mtp_checkpoint,
            quiet=flags.quiet,
        )
    ensure_bundle_runtime_and_reexec(
        p, bundle_path=default_bundle, quiet=flags.quiet
    )


def main() -> None:
    """Console entry: disable Rich tracebacks for expected CLI failures."""
    app()


if __name__ == "__main__":
    main()
