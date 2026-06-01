# pi05_libero

<p align="right"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Pi0.5 LIBERO VLA; weights [lerobot/pi05_libero_finetuned_v044](https://huggingface.co/lerobot/pi05_libero_finetuned_v044).

**Public preset**: `pi05_libero` ([`src/flashcli/catalog/models.yaml`](../../src/flashcli/catalog/models.yaml)). End users pull one CDN zip; flashcli selects the matching `lib/*.so` for this GPU + Python. Run `flashcli models envs pi05_libero` to check a match on this host.

## Files required to run inference (bundle root)

```text
flashcli-bundle.json
run.py
_pi05_compat.py
lib/
  flash_rt_kernels-*-sm89-cu{124|130}-linux-x86_64-py{310|311|312}.so
  flash_rt_fa2-*-....so
flash_rt/                 # trimmed Python tree (no .so inside)
```

Weights are downloaded by flashcli to `~/.flashcli/models/pi05_libero/checkpoint/`, not shipped in the zip.

## End users

```bash
pip install flashcli
flashcli run pi05_libero --prompt "..." --image /path/to/base.jpg
```

## Maintainers: release bundle

### FA2 and SM120

Matrix artifacts are labeled **sm89**, but `requires.sm` includes **120**. FA2 strategy depends on the CUDA line:

| CUDA line | FA2 |
|-----------|-----|
| **cu124** (nvcc 12.4) | sm_89 AOT only (nvcc 12.4 cannot build `compute_120`) |
| **cu130** (nvcc 13.x) | sm_80 + sm_120 + PTX (required for SM120 users) |

**SM120 hosts** must match `*-cu130-*` cells. Do not publish cu130 builds with `--fa2-native-only`. Local SM89-only dev: `build.sh --fa2-native-only`.

### One-command release (recommended)

Linux host with **Docker + NVIDIA GPU**:

```bash
cd flashcli/bundles/pi05_libero
bash release.sh --clean
```

Output example: `dist/flashcli-bundle-pi05-{abi}-sm89-multi-linux-x86_64-{timestamp}.zip`

### Step-by-step (host with cu124 + cu130)

```bash
cd flashcli
bash scripts/build_release_matrix.sh --bundle pi05_libero --check-only
bash scripts/release_bundle.sh --bundle pi05_libero --clean --cuda-tag 124
bash scripts/release_bundle.sh --bundle pi05_libero --cuda-tag 130
flashcli bundle validate bundles/pi05_libero
```

Use `--native` instead of Docker when both CUDA toolkits are on the host.

### After release

1. Smoke-test: `flashcli run pi05_libero --bundle bundles/pi05_libero --benchmark 5`
2. Upload `dist/*.zip` to CDN
3. Update `src/flashcli/catalog/models.yaml` → `pi05_libero.bundle.zip`
4. Verify on SM120 (e.g. RTX PRO 5000)

### Local single-env dev

```bash
bash build.sh --repo-root /path/to/FlashRT
flashcli bundle validate .
```

See [docs/runtime-matrix.md](../../docs/runtime-matrix.md) for the full matrix layout.

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

### `no kernel image is available for execution on the device` (FA2 / SM120)

Usually an **old bundle** or **wrong CUDA cell** on **SM120**: match `sm120-cu130-*` (not cu124). Rebuild with current release scripts.

### `'GemmRunner' object has no attribute 'fp8_nt_dev'`

On SM89, `_pi05_compat.py` shims older `.so` builds, or rebuild FlashRT with `fp8_nt_dev`.

### `FvkContext is already registered`

Use current flashcli; native modules are registered once per process.
