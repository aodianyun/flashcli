; FlashServer Windows UI installer (Inno Setup 6+).
;
; Build on Windows after scripts/build_go.sh has produced dist/go:
;   powershell -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1
;
; The installer is a thin UI wrapper around flashserver-setup.exe. It bundles
; the Linux payload so the WSL install does not need a second network fetch.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\dist\go"
#endif

[Setup]
AppId={{D3F7A5E2-8C1B-4F6A-9E2D-7B4C1A9F3E21}
AppName=FlashServer
AppVersion={#AppVersion}
AppPublisher=FlashHub
AppPublisherURL=https://flashhub.top
DefaultDirName={autopf}\FlashServer
DefaultGroupName=FlashServer
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\..\dist\windows
OutputBaseFilename=FlashServer-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\payload\flashserver-setup.exe
SetupLogging=yes
UsePreviousAppDir=yes
CloseApplications=no

[Files]
Source: "{#PayloadDir}\flashserver-setup-windows-amd64.exe"; DestDir: "{app}\payload"; DestName: "flashserver-setup.exe"; Flags: ignoreversion
Source: "{#PayloadDir}\flashcli-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion
Source: "{#PayloadDir}\flashserver-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion
Source: "{#PayloadDir}\flashcli-linux-arm64"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#PayloadDir}\flashserver-linux-arm64"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#PayloadDir}\sha256sums.txt"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist

[Run]
Filename: "{app}\payload\flashserver-setup.exe"; Parameters: "--backend wsl --bin-dir ""{app}\payload"""; StatusMsg: "Installing WSL2 and flashserver..."; Flags: waituntilterminated runhidden

[UninstallRun]
Filename: "{app}\payload\flashserver-setup.exe"; Parameters: "--uninstall"; RunOnceId: "RemoveFlashServerService"; Flags: waituntilterminated runhidden

[Messages]
WelcomeLabel2=This will install FlashServer, enable WSL2/Ubuntu, and configure the resident model scheduler.%n%nAdministrator privileges are required.
FinishedHeadingLabel=FlashServer is installed
FinishedLabel=FlashServer is installed and its service has been started.%n%nOpen http://localhost:8790/health to verify the local scheduler.
