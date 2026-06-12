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

    reg = PresetRegistry()
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


@models_app.command("show")
def models_show(
    preset: str = typer.Argument(..., help="Preset name from models.yaml."),
) -> None:
    """Show catalog bundle source, cached runtime, and install paths (debugging)."""
    import sys

    from flashcli.bundle.catalog import raw_bundle_cfg
    from flashcli.bundle.marker import read_preset_marker, read_runtime_marker
    from flashcli.bundle.runtime_id import runtime_id_from_repo

    p = PresetRegistry().get(preset)
    cfg = raw_bundle_cfg(p)

    typer.echo(f"flashcli: {__version__} ({sys.executable})")
    typer.echo(f"catalog: {config.MODELS_YAML}")
    typer.echo(f"preset: {preset}")
    typer.echo(f"description: {p.description}")
    if p.bundle_variant:
        typer.echo(f"bundle_variant: {p.bundle_variant}")

    repo = str(cfg.get("repo", "")).strip()
    path = str(cfg.get("path", "")).strip()
    if repo:
        typer.echo(f"catalog repo: {repo}")
        typer.echo(f"expected runtime_id: {runtime_id_from_repo(repo, preset)}")
    if path:
        typer.echo(f"catalog path: {path}")

    marker = read_preset_marker(preset) or {}
    if marker:
        typer.echo("cached preset marker:")
        for key in ("repo", "runtime_id", "bundle_root", "env_key", "source", "path"):
            val = marker.get(key)
            if val:
                typer.echo(f"  {key}: {val}")
        cached_repo = str(marker.get("repo", "")).strip()
        if repo and cached_repo and cached_repo != repo:
            typer.echo(
                f"  [!] catalog repo differs from cache — "
                f"run: flashcli bundle sync {preset} --force"
            )
        rid = str(marker.get("runtime_id", "")).strip()
        if rid:
            runtime_marker = read_runtime_marker(rid) or {}
            if runtime_marker.get("manifest_sha256"):
                typer.echo(f"  manifest_sha256: {runtime_marker['manifest_sha256']}")
    else:
        typer.echo("cached preset marker: (none — run flashcli run/serve or bundle sync)")

    typer.echo(f"weights: {'cached' if model_cache.is_cached(preset) else 'missing'}")


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
    from flashcli.bundle.marker import read_preset_marker
    from flashcli.bundle.preflight import host_env_key
    from flashcli.runtime.detect import detect_gpu
    from flashcli import config

    reg = PresetRegistry()
    names = [preset] if preset else reg.list_names()
    gpu = detect_gpu()
    if gpu is None:
        typer.echo("[!] No NVIDIA GPU detected; cannot match an environment.")
    typer.echo(f"catalog file: {config.MODELS_YAML}")
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
                from flashcli.bundle.python_install import ensure_python_for_minor
                import sys as _sys

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
            marker = read_preset_marker(name) or {}
            cached_repo = str(marker.get("repo", "")).strip()
            if cached_repo:
                typer.echo(f"  cached repo: {cached_repo}")
                if cached_repo != repo:
                    typer.echo(
                        f"  [!] catalog repo changed — run: flashcli bundle sync {name} --force"
                    )
            if marker.get("runtime_id"):
                typer.echo(f"  cached runtime_id: {marker['runtime_id']}")
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


@app.command(
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run() -> None:
    """Run inference using the preset's model bundle."""
    import sys

    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.bundle.bundle_options import (
        BundleOptionsError,
        format_run_help,
        parse_run_argv,
        resolve_manifest_for_preset,
        resolve_preset_from_command_argv,
    )
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

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

    if _auto_install_flag(inv.no_auto_install):
        ensure_environment(install_flashcli=True, quiet=inv.quiet)

    try:
        ensure_bundle_runtime_and_reexec(
            p, bundle_path=inv.bundle, quiet=inv.quiet
        )
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@app.command(
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def serve() -> None:
    """Serve unified OpenAI HTTP API via the preset model bundle."""
    import sys

    from flashcli.bundle.preflight import BundleEnvironmentError
    from flashcli.bundle.bundle_options import (
        BundleOptionsError,
        format_serve_help,
        parse_serve_argv,
        resolve_manifest_for_preset,
        resolve_preset_from_command_argv,
    )
    from flashcli.runtime.reexec import ensure_bundle_runtime_and_reexec

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

    if _auto_install_flag(inv.no_auto_install):
        ensure_environment(install_flashcli=True, quiet=inv.quiet)

    try:
        ensure_bundle_runtime_and_reexec(
            p, bundle_path=inv.bundle, quiet=inv.quiet
        )
    except BundleEnvironmentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


if __name__ == "__main__":
    app()
