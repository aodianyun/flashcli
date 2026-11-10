# FlashServer Desktop

Native desktop client for `flashserver`, built with Rust + [egui/eframe](https://github.com/emilk/egui). No WebView: the UI is rendered by egui through `eframe`, so the binary stays small and runs on Windows, Linux and macOS.

## Features

- Overview: GPU environment (driver/CUDA/compute capability/torch/temperature/clocks/power) with a 0-100 utilization/VRAM chart, CPU info with a 0-100 usage chart, and compact two-row service/disk cards (disk title includes the total). A flat status bar shows GPU/VRAM/CPU/RAM percentages.
- Models: one page for local and FlashHub sources.
  - Local: bundle/weight readiness, serve capability (run-only bundles are marked "仅 run"), separate bundle and weight sizes, total size, loaded state, async load with bundle/weight/dependency progress, row details (endpoint/PID/loaded time, unload, copy endpoint).
  - FlashHub: nothing is listed until you search or pick a category; then browse versions with size/file count and load a version directly.
- Logs: `journalctl` tail (last 300 lines, refreshed every second), "清空" switches to new entries only, "另存为…" saves the full log via a native file dialog.
- Settings: start/stop the daemon without elevation; enable/disable auto-start (UAC) through `flashserver-setup`; dark/light theme; API docs; quit.
- Destructive actions (stop service, disable auto-start, unload, quit) require confirmation.
- Live data: WebSocket `/v1/ws` (1 Hz system snapshots + job progress), HTTP polling fallback.

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

- The Windows installer copies the binary to `{app}\FlashServer.exe` and opens it after installation.
- The client looks for `flashserver-setup.exe` in `payload\flashserver-setup.exe`, `..\payload\flashserver-setup.exe` or next to itself; `FLASHSERVER_SETUP_BIN` overrides the path.
- Service start/stop runs `wsl.exe -d Ubuntu -u root systemctl ...` on Windows. Auto-start changes call `flashserver-setup --start-service/--disable-autostart` (UAC).
- Settings (currently the theme) live in `%LOCALAPPDATA%\FlashServer\settings.json`; a UTF-8 BOM is tolerated.

## Keyboard

- `Ctrl+T` — toggle dark/light theme.

## Cross-platform status

The UI, WebSocket client and HTTP client are platform independent. Service control is implemented for Windows/WSL first; Linux uses `systemctl` best-effort, macOS has no flashserver backend yet. Build on each OS with the platform Rust target.
