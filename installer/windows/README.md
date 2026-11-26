# Windows installer

`flashcli-desktop-setup-windows-amd64.exe` is the published Windows UI entry point. It bundles the
Linux payload and invokes the same `flashserver-setup` engine used by the CLI. The local
build artifact keeps a version suffix; `scripts/release_go.sh` publishes the stable name.

## Build

On Windows, build the client, Go assets, and installer in one command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_package.ps1
```

Options: `-SkipClient`, `-SkipGo`, `-GoBin <dir>` (when `go` is not on PATH), `-OutDir <dir>`.

Requirements (checked by the script):

- Go >= 1.24 and Rust MSVC toolchain (`cargo`)
- Inno Setup 6.6+ (`ISCC.exe` on PATH or in the default Program Files location)

The output is written to `dist/windows/flashcli-desktop-setup-windows-amd64-v<version>.exe` and printed with its SHA256.

Manual/low-level path (after the client and `dist/go` assets already exist):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
```

## Runtime flow

```text
UI installer (admin)
  → install payload under %ProgramFiles%\flashcli-desktop\payload
  → flashserver-setup.exe --backend wsl --bin-dir ... --progress-file ...
  → [1/8] reuse or prepare WSL runtime (supported online install options or the older CLI compatibility path)
  → [2/8] register the flashcli-desktop WSL distro (new: import as `flashserver_ubuntu`; legacy `Ubuntu` with config reused)
  → [3/8] enable systemd
  → [4/8] copy flashcli/flashserver into WSL
  → [5/8] write /etc/flashserver/config.json + systemd unit
  → [6/8] start flashserver.service
  → [7/8] create the Windows ONLOGON keepalive task + model firewall rule
  → [8/8] wait for /health
  → launch flashcli-desktop.exe (desktop client, egui/eframe)
```

The progress page streams the setup engine's recent lines (current step, a
heartbeat during long WSL waits, and Ubuntu rootfs download progress) and has a
Cancel button. Cancelling or closing the wizard signals the setup engine through
its per-run cancel file and waits for the current WSL operation to return before
the engine exits; it does not use `taskkill` to cancel setup.

The WSL runtime check accepts either a successful `wsl --status` or a successful
`wsl --list --quiet`; an empty distribution list is still a usable runtime. If
the runtime is not ready, setup parses the CLI option list even when `wsl --help`
exits with code 1. It uses `wsl --install --no-distribution` only when both
options are advertised. After a failed attempt it checks runtime state again,
then tries `--web-download` at most once when that option is also advertised.
Permission failures, pending restarts, timeouts, and unsupported options stop
the fallback. The error preserves each attempted command result.

An older CLI that does not advertise `--no-distribution` follows a separate
path. Setup enables only Windows features confirmed disabled by a read-only
query, then requests a restart. If both features are enabled and the CLI
advertises `--update`, setup runs that command and rechecks the runtime. If
the feature state or a safe command cannot be confirmed, setup stops with a
specific compatibility error. It never runs bare `wsl --install`, which could
add the default Ubuntu distribution.

Setup invokes DISM only when a read-only query identifies the specific Windows
feature as disabled. Unknown or pending states do not trigger a DISM change.
DISM exit code 3010 requests a Windows restart; setup never restarts Windows.
The installer error dialog identifies
`%LOCALAPPDATA%\flashcli-desktop\logs\setup.log` and shows recent output. It
does not open a browser or direct users to a manual WSL MSI download. Setup
never downloads or installs an MSI automatically.

The API port defaults to `8790`. If Windows has that port in a Hyper-V/WinNAT
excluded range (bind fails with access denied), setup tries `18790`, `28790`,
and so on, writes the chosen port into the WSL config, and records the Windows
URL in `%LOCALAPPDATA%\flashcli-desktop\api-url.txt`. The client and installer read
that file, so no manual port configuration is needed.

Windows-side state moved from `%LOCALAPPDATA%\FlashServer` to
`%LOCALAPPDATA%\flashcli-desktop`, and the default WSL data directory from
`FlashServerWSL` to `flashcli-desktop-wsl`. The setup engine renames the legacy
state directory on first run, so existing settings, the API URL, and the distro
marker are kept. An existing install keeps its previous directory on upgrade
(`UsePreviousAppDir=yes`); a clean install uses `%ProgramFiles%\flashcli-desktop`.

The setup backend holds a per-session Windows mutex for the whole run so two
instances cannot truncate or interleave the UI's fixed `logs\setup.log`. Each
run also writes `logs\setup-run-<UTC timestamp>-<PID>-<sequence>.log`. Before every truncation of the fixed setup.log, the backend archives its
previous content, even if older per-run files exist: a failed per-run write may
have left the fixed file as the only complete copy. Archives are redacted.
Normal writes still update both files in real time and sync them after each
write. Failed writes, short writes, and sync failures warn on stderr and the UI
progress channel; persistence cannot be guaranteed on a full or failing disk.
Successful log initialization prunes only owned run logs to 20 files / 100 MiB;
unknown files and MSI diagnostics are left alone. The Inno progress file is
unique to the installer process.

The payload also contains `flashcli-bundle.tar.gz`. Setup extracts it under
`/usr/local/share/flashcli/flashcli-bundle` and writes
`FLASHCLI_BUNDLE_PIP_SPEC` to `~/.flashcli/install.env`; bundle venv creation no
longer needs a GitHub clone from WSL.

Payload contents: `flashserver-setup.exe` (the WSL setup engine),
`flashcli-linux-amd64`, `flashserver-linux-amd64`, `sha256sums.txt`, and
`flashcli-bundle.tar.gz`. The installer is x64-only
(`ArchitecturesAllowed=x64`) and WSL2 on x64 Windows is amd64, so the arm64
pair is not bundled. Setup verifies local Linux binaries against the checksum
manifest, ELF architecture, and build version. It downloads release assets
only when no local payload binaries are found; incomplete or invalid local
payloads produce an explicit error.

Uninstall asks four optional cleanup checkboxes (model caches, the `flashcli`
CLI, client settings, and the whole flashcli-desktop WSL distro) and passes them to
`flashserver-setup --uninstall` (`--purge-models`, `--remove-cli`,
`--purge-settings`, `--purge-distro`). A select-all checkbox toggles all four;
selecting the distro forces (and disables) the model/CLI options because they
live inside it. Silent uninstall keeps all data.
`--purge-distro` runs `wsl --unregister <distro>` (read from `distro.txt`): it
deletes the virtual disk and frees the space immediately, but everything inside
is lost. The other options only free space inside the VHDX (use `diskpart
compact` or move the distro to reclaim it). The setup engine runs from
`CurUninstallStepChanged` because `[UninstallRun]` constants are expanded at
install time; `--purge-settings` removes `%LOCALAPPDATA%\flashcli-desktop` (client
settings and `logs\setup.log`) after setup exits. Model caches in
`%USERPROFILE%\.flashcli` are only removed by `--purge-models`.

The install wizard also asks for a **WSL data directory** (default: a sibling of
the install directory, e.g. `D:\software\flashcli-desktop-wsl` when installing to
`D:\software\flashcli-desktop`; `%LOCALAPPDATA%\flashcli-desktop-wsl` when installing under
`Program Files`) and passes it as `--wsl-dir`. If WSL runtime preparation
cannot complete, setup reports the specific failure and attempted commands in
the error dialog; review
`%LOCALAPPDATA%\flashcli-desktop\logs\setup.log` for details. Separately, after the runtime is ready, setup
downloads the Ubuntu 24.04 cloud rootfs (Tsinghua/USTC mirrors, then
cloud-images.ubuntu.com) and imports it; `--distro-rootfs FILE` selects a local
tarball for offline distro installation. This rootfs is not the WSL runtime
installer. Model
weights and runtimes live inside the FlashServer-owned ext4.vhdx. A new
flashserver_ubuntu is imported directly into the selected directory with
wsl --import. An existing dedicated distro at the same location is reused.
If its location differs, setup attempts a target-only terminate followed by
wsl --manage <distro> --move <path>, then verifies the registered BasePath and
ext4.vhdx. If that move fails, setup stops with an error unless the user
explicitly selected the optional all-WSL shutdown checkbox. With that consent,
it checks the source and destination again, shuts down all distributions, and
retries once. A failed or unverified move never reports installation success.
Existing legacy Ubuntu distributions are not automatically moved. The VHDX
does not shrink when files are deleted later; compact it using WSL tools.

The wizard sends cancellation through a per-run file instead of killing the
setup process tree. An active `wsl --import` or `wsl --manage --move` command
is allowed to return before setup checks registration and stops; later install
steps do not run. The wizard waits for the backend's final status after a
cancellation request, including during a long storage command. Inspect the
run log before restarting Setup. The same run lock prevents a concurrent
restart.

The installer shows a live progress page and parses the setup progress file
(`[n/8] step` lines plus a final `DONE <code>`). Exit codes: `0` ready, `3`
restart required to finish enabling WSL2, `2` error. On exit `3` the client is
not launched; restart Windows and run the installer again (setup is idempotent).
On success the finished page means the environment was verified (service active
and `/health` returning 200), not merely that files were copied.

If Windows requires a reboot to finish enabling WSL2, the first run stops at
step 1 with the restart message. Run the installer again after reboot.

## Clean Windows VM test

Run these checks on disposable Windows 10 2004+ / Windows 11 x64 VMs with
nested virtualization enabled. Keep separate VM snapshots for a machine without
WSL and a machine with a ready WSL runtime but no registered distributions.

1. On the no-WSL snapshot, verify both `wsl.exe --status` and
   `wsl.exe --list --quiet` fail. Run Setup. If the CLI advertises
   `--no-distribution`, the default WSL install is tried once and the supported
   `--web-download` fallback runs at most once after the runtime recheck. For
   older CLI help, verify that only confirmed disabled Windows features are
   enabled and that bare `wsl --install` is never run. Restart when Setup
   requests it, then verify any advertised `wsl --update` and runtime recheck.
2. On the ready-runtime snapshot, verify `wsl.exe --status` or
   `wsl.exe --list --quiet` succeeds while no Linux distribution is registered.
   Setup should reuse the runtime and must not invoke either WSL runtime install
   command; it should proceed to create the FlashServer-owned distribution.
3. With a disposable second distribution running, request a WSL data-directory
   move. Setup may move only the FlashServer target while the other distro runs. Without the explicit all-WSL shutdown checkbox it must not invoke global `wsl --shutdown`; a failed move must stop setup.
4. Check `logs\setup-run-*.log` and `logs\setup.log`: the former retains one
   file per run, while the latter shows the current run for the Inno UI when
   the compatibility file can be safely updated. If not, Setup preserves the
   old file and reports the per-run log path. Start a second installer during
   a run and confirm it exits without changing the first run's logs or progress
   file.
5. Verify independently (the installer may have selected a port other than 8790):
   ```powershell
   $distro = (Get-Content "$env:LOCALAPPDATA\flashcli-desktop\distro.txt").Trim()
   wsl.exe -l -v
   wsl.exe -d $distro -u root systemctl is-active flashserver   # active
   $url = (Get-Content "$env:LOCALAPPDATA\flashcli-desktop\api-url.txt").Trim()
   (Invoke-WebRequest -UseBasicParsing "$url/health").StatusCode  # 200
   ```
6. Confirm the client opens, the overview shows the service running, and
   auto-start is enabled. Re-run the installer to cover the repair path.

## Notes

- The UI is only a wrapper; automation and troubleshooting should use
  `flashserver-setup.exe` directly.
- The desktop client (`flashcli-desktop.exe`) talks to the same HTTP/WebSocket API;
  its API reference is served at `http://localhost:8790/docs`.
