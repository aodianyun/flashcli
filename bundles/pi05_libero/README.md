# pi05_libero

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

Pi0.5 LIBERO VLA; weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044).

**Public preset**: `pi05_libero` ([`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)). End users sync runtime from FlashHub via `bundle.repo`; flashcli matches manifest `runtime` env keys and loads `.so` from `runtime/<env-key>/`. Run `flashcli models envs pi05_libero` to check a match on this host.

## Files required to run inference (after sync)

```text
flashcli-bundle.json
run.py
_pi05_compat.py
flash_rt/
runtime/<env-key>/         # *.so for this host
```

Weights are downloaded by flashcli to `~/.flashcli/models/pi05_libero/checkpoint/`, not shipped in the bundle.

## End users

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## Troubleshooting

### HuggingFace weight download fails (`LocalEntryNotFoundError`)

The bundle is runtime-only; ~7.5GB weights are fetched from the Hub. In K8s or restricted networks, both `huggingface.co` and `hf-mirror.com` may fail with this error (usually DNS/firewall/proxy, not a missing repo).

```bash
rm -rf ~/.flashcli/models/pi05_libero/checkpoint
export HF_ENDPOINT=https://hf-mirror.com   # pin mirror only; default is official Hub then mirror fallback
flashcli pull pi05_libero
```

Pre-download on a reachable host, then `flashcli run pi05_libero --bundle bundles/pi05_libero --checkpoint ./checkpoint --image ...`.

`--bundle` must be a directory containing `flashcli-bundle.json` (e.g. `bundles/pi05_libero` or `bundles/pi05_libero/dist/`), not a `.zip` archive.

### `no kernel image is available for execution on the device`

Usually **wrong GPU** (SM120 is not supported) or a **CUDA cell mismatch** on SM89. Run `flashcli models envs pi05_libero` — expect `sm89-cu124-*` or `sm89-cu130-*`.

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

On SM89, `_pi05_compat.py` shims older `.so` builds, or rebuild FlashRT with `fp8_nt_dev`.

### `FvkContext is already registered`

Use current flashcli; native modules are registered once per process.
