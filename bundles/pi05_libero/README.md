# pi05_libero

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Pi0.5 LIBERO VLA; weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044).

**Public preset**: `pi05_libero` ([`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)). End users pull the CDN zip for their GPU environment via **`bundle.variants`** (published today: `sm89-cu124-linux-x86_64`). Run `flashcli models envs pi05_libero` to check a match on this host.

## Files required to run inference (bundle root)

```text
flashcli-bundle.json
run.py
_pi05_compat.py
flash_rt_kernels.so
flash_rt_fa2.so
flash_rt/                 # trimmed Python tree (no .so inside)
```

Weights are downloaded by flashcli to `~/.flashcli/models/pi05_libero/checkpoint/`, not shipped in the zip.

## End users

```bash
pip install flashcli
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## Maintainers: assemble bundle

**Linux + NVIDIA GPU** (SM89 or SM120):

```bash
cd flashcli/bundles/pi05_libero
bash build.sh --repo-root /path/to/FlashRT
bash pack.sh --sm 89                  # release zip (cuda tag auto from nvcc, typically cu124)
```

Register the zip URL under the matching environment key in `src/flashcli/catalog/models.yaml`, e.g.:

```yaml
bundle:
  variants:
    sm89-cu124-linux-x86_64:
      zip: https://cdn.../flashcli-bundle-pi05-main-sm89-cu124-linux-x86_64.zip
```

`build.sh` stages only the Pi0.5 RTX `flash_rt/` subtree and copies `flash_rt_kernels.so` + `flash_rt_fa2.so` only.

Do **not** ship `requirements-runtime.txt` in the release zip — dependencies live in `flashcli-bundle.json` → `python_dependencies`.

```bash
flashcli bundle validate "$(pwd)/bundles/pi05_libero"
flashcli run pi05_libero --bundle "$(pwd)/bundles/pi05_libero" --image /path/to/base.jpg
```

## Troubleshooting

### HuggingFace weight download fails (`LocalEntryNotFoundError`)

The release zip is runtime-only; ~7.5GB weights are fetched from the Hub. In K8s or restricted networks, both `huggingface.co` and `hf-mirror.com` may fail with this error (usually DNS/firewall/proxy, not a missing repo).

```bash
rm -rf ~/.flashcli/models/pi05_libero/checkpoint
export HF_ENDPOINT=https://hf-mirror.com   # pin mirror only; default is official Hub then mirror fallback
flashcli pull pi05_libero
```

Pre-download on a reachable host, then `flashcli run pi05_libero --bundle bundles/pi05_libero --checkpoint ./checkpoint --image ...`.

`--bundle` must be a directory containing `flashcli-bundle.json` (e.g. `bundles/pi05_libero` or an extracted `dist/flashcli-bundle-pi05-*` folder), not the `.zip` file.

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

On SM89, `_pi05_compat.py` shims older `.so` builds, or rebuild FlashRT with `fp8_nt_dev`.

### `FvkContext is already registered`

Use current flashcli; native modules are registered once per process.
