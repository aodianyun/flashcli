# FlashServer Desktop

Native desktop client for `flashserver`, built with Rust + [egui/eframe](https://github.com/emilk/egui). No WebView: the UI is rendered by egui through `eframe`, so the binary stays small and runs on Windows, Linux and macOS.

## Features

- Overview: GPU environment (driver/CUDA/compute capability/torch/temperature/clocks/power) with a 0-100 utilization/VRAM chart, CPU info with a 0-100 usage chart, and compact two-row service/disk cards (disk title includes the total). A flat status bar shows GPU/VRAM/CPU/RAM percentages.
- Models: one page for local and FlashHub sources.
  - Local: bundle/runtime/weight readiness, serve capability (run-only bundles are marked "仅 run"), separate bundle/runtime/weight sizes, total size, ready/started state, async load (bundle/runtime/weights) and start (serve) progress, row actions (使用 / 更多 → 查看信息 / 查看日志 / Run 冒烟测试 / 停止), and multi-select cache cleanup (all cleanable rows selected by default; started models are skipped). "加载" prepares a model to the ready state; only then can it be started with "启动". Ready run-only models offer a `flashcli run` smoke test in the row menu; started serve models offer one OpenAI-compatible request test inside the 使用 dialog; both show the returned log in a dialog. The 使用 dialog shows the model's serve endpoint, OpenAI-compatible curl examples, API docs, model list, local console, and the request test.
  - FlashHub: nothing is listed until you search or pick a category; then browse versions with size/file count and download a version. Load it from the Local tab, which shows "仅 run" and hides the start action for bundles without a serve entry.
- Logs: server `journalctl` tail or a specific started model's serve log (返回服务日志 switches back), "清空" for server logs, and "另存为…" saves the full log via a native file dialog.
- Settings: start/stop the daemon without elevation; enable/disable auto-start (UAC) through `flashserver-setup`; enable domestic mirrors (pip/HuggingFace/GitHub) for new downloads; clean the shared cache (download cache, base Python, uv) with per-item sizing; dark/light theme; API docs; quit. Model bundles/weights/runtimes are cleaned from the Models page (multi-select), not from Settings.
- API URL: reads `%LOCALAPPDATA%\FlashServer\api-url.txt` (written by setup when the default port 8790 is reserved) and falls back to `http://127.0.0.1:8790`. The settings page shows the selected address.
- Copy actions (Serve address, usage example) show a result toast; the usage example is also selectable.
- Destructive actions (stop service, disable auto-start, stop model, quit) require confirmation.
- Live data: WebSocket `/v1/ws` (1 Hz system snapshots + job progress), HTTP polling fallback.
- Load/start progress shows the bundle ref, current phase (bundle sync, Python runtime/venv, weights for load; serve/health for start), file/byte counts and percentage. Checksum-mismatched downloads are retried. A completed load/start banner disappears after a few seconds.
- Downloads are serialized; load/download/start actions are disabled while a job is active and the current row shows "加载中…/下载中…/启动中…".
- Model size is Bundle + per-model runtime + weights. Weights are shared by `source/repo@revision` and may be repeated across rows, while model totals de-dupe by weights key. Runtime directories are per bundle/version. Settings shows the grouped shared cache (downloads + base Python + uv); model bundles/weights/runtimes are cleaned from the Models page.

## Build (Windows)

Requirements: Rust MSVC toolchain (`rustup default stable-x86_64-pc-windows-msvc`), Windows SDK/MSVC build tools.

The release binary uses the Windows GUI subsystem, so it starts without a console window. `rfd` is used for the native "Save As" dialog.

```powershell
cd desktop
cargo build --release
# desktop/target/release/FlashServer.exe (~4.7 MB)
```

`build.rs` embeds `build/icon.ico` (generated from `ui/icon.png`) into the executable; the window icon is loaded from the same PNG.

## Run / package

- The Windows installer is produced by `scripts/build_windows_package.ps1` (client + Go assets + Inno Setup) and copies the binary to `{app}\FlashServer.exe`, then opens it after installation.
- The client looks for `flashserver-setup.exe` in `payload\flashserver-setup.exe`, `..\payload\flashserver-setup.exe` or next to itself; `FLASHSERVER_SETUP_BIN` overrides the path.
- Service start/stop runs `wsl.exe -d Ubuntu -u root systemctl ...` on Windows. Auto-start changes call `flashserver-setup --enable-autostart/--disable-autostart` (UAC) and never start/stop the service. Long operations use a modal progress overlay plus a result toast; the elevated console is hidden.
- Settings (currently the theme) live in `%LOCALAPPDATA%\FlashServer\settings.json`; a UTF-8 BOM is tolerated.

## Keyboard

- `Ctrl+T` — toggle dark/light theme.

## Cross-platform status

The UI, WebSocket client and HTTP client are platform independent. Service control is implemented for Windows/WSL first; Linux uses `systemctl` best-effort, macOS has no flashserver backend yet. Build on each OS with the platform Rust target.
