# Windows installer

`FlashServer-Setup-<version>.exe` is the Windows UI entry point. It bundles the
Linux payload and invokes the same `flashserver-setup` engine used by the CLI.

## Build

On Windows, build the client, Go assets, and installer in one command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1
```

Options: `-SkipClient`, `-SkipGo`, `-GoBin <dir>` (when `go` is not on PATH), `-OutDir <dir>`.

Requirements (checked by the script):

- Go >= 1.24 and Rust MSVC toolchain (`cargo`)
- Inno Setup 6 (`ISCC.exe` on PATH or in the default Program Files location)

The output is written to `dist/windows/FlashServer-Setup-<version>.exe` and printed with its SHA256.

Manual/low-level path (after the client and `dist/go` assets already exist):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
```

## Runtime flow

```text
UI installer (admin)
  → install payload under %ProgramFiles%\FlashServer\payload
  → run flashserver-setup.exe --backend wsl --bin-dir ...
  → WSL2 / Ubuntu / systemd / flashserver.service
  → Windows ONSTART startup task
  → health check via localhost:8790
  → launch FlashServer.exe (desktop client, egui/eframe)
```

The UI installer runs the setup engine hidden and reports the final status in
the wizard. If Windows requires a reboot to finish enabling WSL2, reboot and
run the installer again; the setup engine is idempotent.

## Notes

- The UI is only a wrapper; automation and troubleshooting should use
  `flashserver-setup.exe` directly.
- The desktop client (`FlashServer.exe`) talks to the same HTTP/WebSocket API;
  its API reference is served at `http://localhost:8790/docs`.
