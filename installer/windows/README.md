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
  → flashserver-setup.exe --backend wsl --bin-dir ... --progress-file ...
  → [1/8] check/enable WSL2 (`wsl --install --no-distribution`, DISM fallback)
  → [2/8] install/register Ubuntu
  → [3/8] enable systemd
  → [4/8] copy flashcli/flashserver into WSL
  → [5/8] write /etc/flashserver/config.json + systemd unit
  → [6/8] start flashserver.service
  → [7/8] create the Windows ONLOGON keepalive task
  → [8/8] wait for /health
  → installer re-checks systemctl + /health
  → launch FlashServer.exe (desktop client, egui/eframe)
```

The installer shows a live progress page and parses the setup progress file
(`[n/8] step` lines plus a final `DONE <code>`). Exit codes: `0` ready, `3`
restart required to finish enabling WSL2, `2` error. On exit `3` the client is
not launched; restart Windows and run the installer again (setup is idempotent).
On success the finished page means the environment was verified (service active
and `/health` returning 200), not merely that files were copied.

If Windows requires a reboot to finish enabling WSL2, the first run stops at
step 1 with the restart message. Run the installer again after reboot.

## Clean Windows VM test

Use a Windows 10 2004+/Windows 11 x64 VM with internet access and nested
virtualization enabled (VT-x/AMD-V).

1. Confirm `wsl.exe --status` fails and `wsl.exe -l -v` lists no Ubuntu.
2. Run the installer. The setup progress page must appear; the first run may
   stop at step 1 and ask for a restart.
3. Restart, run the installer again, and confirm steps 1-8 complete with
   "FlashServer is installed and ready."
4. Verify independently:
   ```powershell
   wsl.exe -l -v
   wsl.exe -d Ubuntu -u root systemctl is-active flashserver   # active
   (Invoke-WebRequest -UseBasicParsing http://localhost:8790/health).StatusCode  # 200
   ```
5. Confirm the client opens, the overview shows the service running, and
   auto-start is enabled. Re-run the installer to cover the repair path.

## Notes

- The UI is only a wrapper; automation and troubleshooting should use
  `flashserver-setup.exe` directly.
- The desktop client (`FlashServer.exe`) talks to the same HTTP/WebSocket API;
  its API reference is served at `http://localhost:8790/docs`.
