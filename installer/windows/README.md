# Windows installer

`FlashServer-Setup-<version>.exe` is the Windows UI entry point. It bundles the
Linux payload and invokes the same `flashserver-setup` engine used by the CLI.

## Build

On Windows, after building the release assets:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
```

Requirements:

- Inno Setup 6 (`ISCC.exe` on PATH or in the default Program Files location)
- `dist/go/flashserver-setup-windows-amd64.exe`
- `dist/go/flashcli-linux-*` and `dist/go/flashserver-linux-*`

The output is written to `dist/windows/FlashServer-Setup-<version>.exe`.

## Runtime flow

```text
UI installer (admin)
  → install payload under %ProgramFiles%\FlashServer\payload
  → run flashserver-setup.exe --backend wsl --bin-dir ...
  → WSL2 / Ubuntu / systemd / flashserver.service
  → Windows ONSTART startup task
  → health check via localhost:8790
```

The UI installer runs the setup engine hidden and reports the final status in
the wizard. If Windows requires a reboot to finish enabling WSL2, reboot and
run the installer again; the setup engine is idempotent.

## Notes

- The UI is only a wrapper; automation and troubleshooting should use
  `flashserver-setup.exe` directly.
- A future Windows desktop client can use the existing flashserver API for
  model load/unload and resource display.
