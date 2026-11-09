# FlashServer Desktop

Native desktop client for `flashserver`, built with Rust + [Slint](https://slint.dev/). No WebView: the UI is rendered by Slint, so the process stays small and works on Windows, Linux and macOS.

## Features

- Overview: GPU utilization/VRAM, CUDA/driver/SM/torch, CPU load and per-core usage, RAM/swap, 5-minute GPU/CPU charts.
- Models: cached bundle list with bundle/weight readiness, ref input, async load with progress.
- Loaded: endpoint copy, unload, PID/load time.
- Logs: recent server log lines.
- Service: start/stop the daemon without elevation; enable/disable auto-start (UAC) through `flashserver-setup`.
- Live data: WebSocket `/v1/ws` (1 Hz system snapshots + job progress), HTTP fallback.

## Build (Windows)

Requirements: Rust MSVC toolchain (`rustup default stable-x86_64-pc-windows-msvc`), Windows SDK/MSVC build tools.

```powershell
cd desktop
cargo build --release
# desktop/target/release/FlashServer.exe
```

The release binary is about 10 MB. The app forces `SLINT_BACKEND=winit-software` so it also renders on VMs/RDP where OpenGL is unavailable; set `SLINT_BACKEND` yourself to override.

## Run / package

- The Windows installer copies the binary to `{app}\FlashServer.exe` and opens it after installation.
- The client looks for `flashserver-setup.exe` in `payload\flashserver-setup.exe`, `..\payload\flashserver-setup.exe` or next to itself; `FLASHSERVER_SETUP_BIN` overrides the path.
- Service start/stop runs `wsl.exe -d Ubuntu -u root systemctl ...` on Windows. Auto-start changes call `flashserver-setup --start-service/--stop-service` (UAC).

## Cross-platform status

The UI, WebSocket client and HTTP client are platform independent. Service control is implemented for Windows/WSL first; Linux uses `systemctl` best-effort, macOS has no flashserver backend yet. Build on each OS with the platform Rust target.
