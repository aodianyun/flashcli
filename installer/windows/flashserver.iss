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
SetupIconFile=flashserver.ico
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
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#PayloadDir}\flashserver-setup-windows-amd64.exe"; DestDir: "{app}\payload"; DestName: "flashserver-setup.exe"; Flags: ignoreversion
Source: "{#PayloadDir}\FlashServer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\flashcli-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion
Source: "{#PayloadDir}\flashserver-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion
Source: "{#PayloadDir}\flashcli-linux-arm64"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#PayloadDir}\flashserver-linux-arm64"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#PayloadDir}\sha256sums.txt"; DestDir: "{app}\payload"; Flags: ignoreversion skipifsourcedoesntexist

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut to the FlashServer client"; GroupDescription: "Additional icons:"

[Icons]
Name: "{autoprograms}\FlashServer"; Filename: "{app}\FlashServer.exe"
Name: "{autodesktop}\FlashServer"; Filename: "{app}\FlashServer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlashServer.exe"; Description: "Launch FlashServer"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM FlashServer.exe"; Flags: runhidden; RunOnceId: "StopFlashServerClient"
Filename: "{app}\payload\flashserver-setup.exe"; Parameters: "--uninstall"; RunOnceId: "RemoveFlashServerService"; Flags: waituntilterminated runhidden

[Code]
var
  SetupOK: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    SetupOK := Exec(
      ExpandConstant('{app}\payload\flashserver-setup.exe'),
      '--backend wsl --bin-dir "' + ExpandConstant('{app}\payload') + '"',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    if not SetupOK then
      MsgBox('FlashServer setup did not complete (exit code ' + IntToStr(ResultCode) + ').' + #13#10 +
        'See the log: %USERPROFILE%\.flashcli\logs\setup.log', mbError, MB_OK);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if SetupOK then
      WizardForm.FinishedLabel.Caption :=
        'FlashServer is installed and running.' + #13#10 + #13#10 +
        'Client: started automatically' + #13#10 +
        'API docs: http://localhost:8790/docs'
    else
      WizardForm.FinishedLabel.Caption :=
        'FlashServer installation needs attention.' + #13#10 + #13#10 +
        'Check %USERPROFILE%\.flashcli\logs\setup.log and run the installer again.';
  end;
end;

[Messages]
WelcomeLabel2=This will install FlashServer, enable WSL2/Ubuntu, and configure the resident model scheduler.%n%nAdministrator privileges are required.
FinishedHeadingLabel=FlashServer is installed
FinishedLabel=FlashServer is installed and its service has been started.%n%nThe desktop client is opened automatically; API docs are at http://localhost:8790/docs.
