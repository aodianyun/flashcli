# pi05_libero

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a> · <a href="QUICKSTART.md">Quick start</a></p>

Pi0.5 LIBERO VLA; weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044).

**Public preset**: `pi05_libero` ([`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)). End users sync runtime from FlashHub via `bundle.repo`; flashcli matches manifest `runtime` env keys and installs `.so` under `lib/`. Run `flashcli models envs pi05_libero` to check a match on this host.

## Files required to run inference (after sync)

```text
flashcli-bundle.json
run.py
_pi05_compat.py
lib/                       # *.so for this host (from runtime/<env-key>/)
flash_rt/
```

Weights are downloaded by flashcli to `~/.flashcli/models/pi05_libero/checkpoint/`, not shipped in the bundle.

## End users

See **[QUICKSTART.md](QUICKSTART.md)** for copy-paste commands.

```bash
pip install flashcli
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## Maintainers: release bundle

Full step-by-step guide: **[docs/bundle_builder_guide.md](../../docs/bundle_builder_guide.md)** (mirrors, local build, matrix release, FlashHub upload).

**Supported GPU**: **SM89 only** (Ada, e.g. RTX 4090).

```bash
cd flashcli
pip install -e ./flashcli-bundle -e .
bash scripts/release_bundle.sh --bundle pi05_libero --clean
```

Matrix: **sm89 × cu124/cu130 × py312** (`release-matrix.env`). Local single-env dev:

```bash
bash bundles/pi05_libero/build.sh --repo-root /path/to/FlashRT
flashcli bundle validate bundles/pi05_libero
```

FA2 build strategy: [docs/runtime-matrix.md](../../docs/runtime-matrix.md).

## Troubleshooting

### HuggingFace weight download fails (`LocalEntryNotFoundError`)

The bundle is runtime-only; ~7.5GB weights are fetched from the Hub. In K8s or restricted networks, both `huggingface.co` and `hf-mirror.com` may fail with this error (usually DNS/firewall/proxy, not a missing repo).

```bash
rm -rf ~/.flashcli/models/pi05_libero/checkpoint
export HF_ENDPOINT=https://hf-mirror.com   # pin mirror only; default is official Hub then mirror fallback
flashcli pull pi05_libero
```

Pre-download on a reachable host, then `flashcli run pi05_libero --bundle bundles/pi05_libero --checkpoint ./checkpoint --image ...`.

`--bundle` must be a directory containing `flashcli-bundle.json` (e.g. `bundles/pi05_libero` or an extracted `dist/flashcli-bundle-pi05-*` folder), not the `.zip` file.

### `no kernel image is available for execution on the device`

Usually **wrong GPU** (SM120 is not supported) or a **CUDA cell mismatch** on SM89. Run `flashcli models envs pi05_libero` — expect `sm89-cu124-*` or `sm89-cu130-*`.

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

On SM89, `_pi05_compat.py` shims older `.so` builds, or rebuild FlashRT with `fp8_nt_dev`.

### `FvkContext is already registered`

Use current flashcli; native modules are registered once per process.
