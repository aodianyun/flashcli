# pi05_libero

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

Pi0.5 LIBERO VLA; weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044).

**Ref**: `flashcli-bundle/pi05_libero:1.0.4`. End users sync runtime from FlashHub; flashcli matches manifest `runtime` env keys and loads `.so` from `runtime/<env-key>/`. Run `flashcli models envs flashcli-bundle/pi05_libero:1.0.4` to check a match on this host.

## Files required to run inference (after sync)

```text
flashcli-bundle.json
run.py                    # script entry (main)
run_engine.py             # engine entry (RunEngine); see flashcli-bundle.engine.json
_pi05_infer.py
_pi05_compat.py
flash_rt/
runtime/<env-key>/         # *.so for this host
```

Weights are downloaded by flashcli to `~/.flashcli/models/pi05_libero/1.0.4/checkpoint/`, not shipped in the bundle.

## Entry modes

| File | Role |
|------|------|
| `flashcli-bundle.json` | **Default script**: `run.main(argv)`; does **not** `import flashcli_bundle` |
| `flashcli-bundle.engine.json` | **Engine example**: `run_engine.RunEngine`; `cp flashcli-bundle.engine.json flashcli-bundle.json` to try engine locally |

`run.py` (script) and `run_engine.py` (engine) share `_pi05_infer.py`; script reads paths from `FLASHCLI_CHECKPOINT` and related env vars only.

## End users

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
flashcli run flashcli-bundle/pi05_libero:1.0.4 --prompt "..." --image /path/to/base.jpg
```

## Troubleshooting

### HuggingFace weight download fails (`LocalEntryNotFoundError`)

The bundle is runtime-only; ~7.5GB weights are fetched from the Hub. In K8s or restricted networks, both `huggingface.co` and `hf-mirror.com` may fail with this error (usually DNS/firewall/proxy, not a missing repo).

```bash
rm -rf ~/.flashcli/models/*/checkpoint   # or remove the ref's cache dir from flashcli models show
export HF_ENDPOINT=https://hf-mirror.com   # pin mirror only; default is official Hub then mirror fallback
flashcli pull flashcli-bundle/pi05_libero:1.0.4
```

Pre-download on a reachable host, then `flashcli run bundles/pi05_libero --checkpoint ./checkpoint --image ...`.

Local dev: positional ref must be a directory containing `flashcli-bundle.json` (e.g. `bundles/pi05_libero` or `bundles/pi05_libero/dist/`), not a `.zip` archive.

### `no kernel image is available for execution on the device`

Usually **wrong GPU/CUDA cell** or a **stale FlashHub runtime**. Run `flashcli models envs flashcli-bundle/pi05_libero:1.0.4` — expect `sm89-cu124-*`, `sm89-cu130-*`, or `sm120-cu130-*`.

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

On SM89, `_pi05_compat.py` shims older `.so` builds, or rebuild FlashRT with `fp8_nt_dev`.

### `FvkContext is already registered`

Use current flashcli; native modules are registered once per process.
