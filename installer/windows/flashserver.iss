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
OutputBaseFilename=flashserver-setup-windows-amd64-v{#AppVersion}
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
Source: "{#PayloadDir}\flashcli-bundle.tar.gz"; DestDir: "{app}\payload"; Flags: ignoreversion
; x64-only installer: WSL2 is amd64 here, so the arm64 pair is not shipped.
Source: "{#PayloadDir}\flashcli-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion
Source: "{#PayloadDir}\flashserver-linux-amd64"; DestDir: "{app}\payload"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut to the FlashServer client"; GroupDescription: "Additional icons:"

[Icons]
Name: "{autoprograms}\FlashServer"; Filename: "{app}\FlashServer.exe"
Name: "{autodesktop}\FlashServer"; Filename: "{app}\FlashServer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlashServer.exe"; Description: "Launch FlashServer"; Flags: postinstall nowait skipifsilent; Check: SetupReady

[Code]
var
  PurgeModels: Boolean;
  RemoveCLI: Boolean;
  PurgeSettings: Boolean;
  SetupOK: Boolean;
  SetupReboot: Boolean;
  SetupError: String;
  ProgressPage: TOutputProgressWizardPage;
  WSLDirPage: TInputDirWizardPage;

// Extra arguments for `flashserver-setup --uninstall`, decided by the
// checkboxes shown before the uninstall starts.
function GetPurgeArgs(Param: String): String;
begin
  Result := '';
  if PurgeModels then
    Result := Result + ' --purge-models';
  if RemoveCLI then
    Result := Result + ' --remove-cli';
  if PurgeSettings then
    Result := Result + ' --purge-settings';
end;

// The Inno uninstaller has no wizard pages, so show a small custom form with
// the optional cleanup choices. Defaults keep all data.
procedure ShowUninstallOptions;
var
  Form: TSetupForm;
  Title: TNewStaticText;
  CbModels, CbCli, CbSettings: TCheckBox;
  Btn: TButton;
begin
  Form := CreateCustomForm();
  try
    Form.Caption := 'FlashServer 卸载选项';
    Form.ClientWidth := ScaleX(540);
    Form.ClientHeight := ScaleY(232);
    Form.Position := poScreenCenter;
    Form.BorderStyle := bsDialog;

    Title := TNewStaticText.Create(Form);
    Title.Parent := Form;
    Title.Left := ScaleX(16);
    Title.Top := ScaleY(14);
    Title.Width := ScaleX(508);
    Title.Caption := '默认保留模型缓存和设置。勾选以下项目会在卸载时一并删除：';

    CbModels := TCheckBox.Create(Form);
    CbModels.Parent := Form;
    CbModels.Left := ScaleX(16);
    CbModels.Top := ScaleY(50);
    CbModels.Width := ScaleX(508);
    CbModels.Caption := '模型缓存、权重和运行环境（~/.flashcli，不可恢复）';
    CbModels.Checked := False;

    CbCli := TCheckBox.Create(Form);
    CbCli.Parent := Form;
    CbCli.Left := ScaleX(16);
    CbCli.Top := ScaleY(84);
    CbCli.Width := ScaleX(508);
    CbCli.Caption := 'flashcli 命令行（/usr/local/bin/flashcli）';
    CbCli.Checked := False;

    CbSettings := TCheckBox.Create(Form);
    CbSettings.Parent := Form;
    CbSettings.Left := ScaleX(16);
    CbSettings.Top := ScaleY(118);
    CbSettings.Width := ScaleX(508);
    CbSettings.Caption := '客户端设置（%LOCALAPPDATA%\FlashServer）';
    CbSettings.Checked := False;

    Btn := TButton.Create(Form);
    Btn.Parent := Form;
    Btn.Caption := '继续卸载';
    Btn.ModalResult := mrOk;
    Btn.Default := True;
    Btn.Left := ScaleX(408);
    Btn.Top := ScaleY(184);
    Btn.Width := ScaleX(116);
    Btn.Height := ScaleY(30);

    Form.ShowModal;
    PurgeModels := CbModels.Checked;
    RemoveCLI := CbCli.Checked;
    PurgeSettings := CbSettings.Checked;
  finally
    Form.Free;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  if UninstallSilent() then
    Exit;
  ShowUninstallOptions;
end;

// [UninstallRun] constants are expanded at install time, so the setup engine
// (and its dynamic cleanup flags) must be started here, at uninstall time.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Args: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM FlashServer.exe', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Args := '--uninstall' + GetPurgeArgs('');
    if not Exec(ExpandConstant('{app}\payload\flashserver-setup.exe'), Args,
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      MsgBox('Could not start flashserver-setup.exe.', mbError, MB_OK)
    else if ResultCode <> 0 then
      MsgBox('flashserver-setup --uninstall exited with code ' +
        IntToStr(ResultCode) + '.' + #13#10#13#10 +
        'See %USERPROFILE%\.flashcli\logs\setup.log.', mbError, MB_OK);
  end
  else if (CurUninstallStep = usPostUninstall) and PurgeSettings then
    // Setup has exited by now, so its setup.log is closed and the whole
    // Windows-side state can go (client settings are removed by setup).
    DelTree(ExpandConstant('{userprofile}\.flashcli'), True, True, True);
end;

function SetupReady: Boolean;
begin
  Result := SetupOK;
end;

function TrimRight(const S: String): String;
var
  I: Integer;
begin
  I := Length(S);
  while (I > 0) and ((S[I] = ' ') or (S[I] = #9) or (S[I] = #13) or (S[I] = #10)) do
    Dec(I);
  Result := Copy(S, 1, I);
end;

{ Returns the last non-empty line that is not a step header or the DONE marker,
  so long WSL downloads can show their own progress text. }
function IsDetailLine(const Value: String): Boolean;
var
  T: String;
begin
  T := Trim(Value);
  Result := (T <> '') and (T[1] <> '[') and (Copy(T, 1, 5) <> 'DONE ') and
    (Copy(T, 1, 17) <> 'flashserver-setup') and
    (Copy(T, 1, 7) <> 'System:') and (Copy(T, 1, 4) <> 'Log:') and
    (Copy(T, 1, 15) <> 'Windows must be');
end;

function LastDetailLine(const S: String): String;
var
  I, StartPos: Integer;
  T: String;
begin
  Result := '';
  StartPos := 1;
  for I := 1 to Length(S) do
  begin
    if (S[I] = #10) or (S[I] = #13) then
    begin
      T := Trim(Copy(S, StartPos, I - StartPos));
      if IsDetailLine(T) then
        Result := T;
      StartPos := I + 1;
    end;
  end;
  T := Trim(Copy(S, StartPos, Length(S) - StartPos + 1));
  if IsDetailLine(T) then
    Result := T;
end;

{ Parses the last "[n/total] step ... ok" line and the final "DONE <code>"
  line written by flashserver-setup --progress-file. }
procedure ParseProgress(const S: String; var Step, Total: Integer;
  var StepText: String; var StepDone, HasDone: Boolean; var DoneCode: Integer);
var
  I, N, StartPos: Integer;
  Num: String;
begin
  Step := 0;
  Total := 0;
  StepText := '';
  StepDone := False;
  HasDone := False;
  DoneCode := -1;
  I := 1;
  while I <= Length(S) do
  begin
    if S[I] = '[' then
    begin
      N := I + 1;
      StartPos := N;
      while (N <= Length(S)) and (S[N] >= '0') and (S[N] <= '9') do
        Inc(N);
      Num := Copy(S, StartPos, N - StartPos);
      if (Num <> '') and (N <= Length(S)) and (S[N] = '/') then
      begin
        Step := StrToIntDef(Num, 0);
        Inc(N);
        StartPos := N;
        while (N <= Length(S)) and (S[N] >= '0') and (S[N] <= '9') do
          Inc(N);
        Num := Copy(S, StartPos, N - StartPos);
        if (Num <> '') and (N <= Length(S)) and (S[N] = ']') then
        begin
          Total := StrToIntDef(Num, 0);
          Inc(N);
          while (N <= Length(S)) and (S[N] = ' ') do
            Inc(N);
          StartPos := N;
          while (N <= Length(S)) and (S[N] <> #13) and (S[N] <> #10) do
            Inc(N);
          StepText := TrimRight(Copy(S, StartPos, N - StartPos));
          StepDone := False;
          if (Length(StepText) >= 3) and
             (Copy(StepText, Length(StepText) - 2, 3) = ' ok') then
          begin
            StepDone := True;
            StepText := TrimRight(Copy(StepText, 1, Length(StepText) - 3));
          end
          else if (Length(StepText) >= 7) and
             (Copy(StepText, Length(StepText) - 6, 7) = ' FAILED') then
          begin
            StepText := TrimRight(Copy(StepText, 1, Length(StepText) - 7));
          end;
          I := N;
          Continue;
        end;
      end;
      I := N + 1;
    end
    else if (S[I] = 'D') and (Copy(S, I, 5) = 'DONE ') and
            ((I = 1) or (S[I - 1] = #10)) then
    begin
      N := I + 5;
      StartPos := N;
      while (N <= Length(S)) and (S[N] >= '0') and (S[N] <= '9') do
        Inc(N);
      Num := Copy(S, StartPos, N - StartPos);
      if Num <> '' then
      begin
        DoneCode := StrToIntDef(Num, -1);
        HasDone := True;
      end;
      I := N;
    end
    else
      Inc(I);
  end;
end;

function LoadProgress(const Path: String; var Step, Total: Integer;
  var StepText: String; var StepDone, HasDone: Boolean;
  var DoneCode: Integer; var LastLog: String): Boolean;
var
  S: String;
  A: AnsiString;
begin
  Step := 0;
  Total := 0;
  StepText := '';
  StepDone := False;
  HasDone := False;
  DoneCode := -1;
  LastLog := '';
  Result := LoadStringFromFile(Path, A);
  if Result then
  begin
    S := A;
    ParseProgress(S, Step, Total, StepText, StepDone, HasDone, DoneCode);
    LastLog := LastDetailLine(S);
  end;
end;

function LogTail(const Path: String; MaxChars: Integer): String;
var
  S: String;
  A: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(Path, A) then
  begin
    S := A;
    if Length(S) > MaxChars then
      S := Copy(S, Length(S) - MaxChars + 1, MaxChars);
    Result := Trim(S);
  end;
end;

function ClientAPIURL: String;
var
  A: AnsiString;
  S: String;
begin
  Result := 'http://127.0.0.1:8790';
  if LoadStringFromFile(GetEnv('LOCALAPPDATA') + '\FlashServer\api-url.txt', A) then
  begin
    S := Trim(String(A));
    if (Copy(S, 1, 7) = 'http://') or (Copy(S, 1, 8) = 'https://') then
      Result := S;
  end;
end;

function HealthOK: Boolean;
var
  ResultCode: Integer;
  ScriptPath, Script: String;
begin
  ScriptPath := ExpandConstant('{tmp}\flashserver-health.ps1');
  Script := 'try {' + #13#10 +
    '  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 ' + #39 +
      ClientAPIURL + '/health' + #39 + #13#10 +
    '  if ($r.StatusCode -eq 200) { exit 0 } else { exit 2 }' + #13#10 +
    '} catch { exit 1 }' + #13#10;
  if not SaveStringToFile(ScriptPath, Script, False) then
  begin
    Result := False;
    Exit;
  end;
  Result := Exec(
    ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function ServiceActive: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sysnative}\wsl.exe'),
    '-d Ubuntu -u root systemctl is-active flashserver',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ Independently confirms the environment is ready: the systemd unit is active
  and the HTTP API answers /health. The setup engine already waits for health,
  so this is a short final gate (and catches a service that died right after). }
function VerifyReady: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to 8 do
  begin
    if ServiceActive and HealthOK then
    begin
      Result := True;
      Exit;
    end;
    Sleep(1500);
  end;
end;

function RunEnvironmentSetup: Boolean;
var
  ResultCode, Step, Total, DoneCode, Attempts: Integer;
  StepText, Detail, ProgressPath, LogPath, ProgressLog, LastLog: String;
  StepDone, HasDone, Started, Ready, LastDone: Boolean;
  LastStep: Integer;
  LastText: String;
  WSLArgs: String;
begin
  Result := False;
  SetupError := '';
  SetupReboot := False;
  ProgressPath := ExpandConstant('{tmp}\flashserver-progress.txt');
  LogPath := GetEnv('USERPROFILE') + '\.flashcli\logs\setup.log';
  DeleteFile(ProgressPath);
  WSLArgs := '';
  if Trim(WSLDirPage.Values[0]) <> '' then
    WSLArgs := ' --wsl-dir "' + WSLDirPage.Values[0] + '"';

  ProgressPage.SetText('Preparing the FlashServer environment',
    'Checking WSL2 and Ubuntu. On a new PC this can take several minutes.');
  ProgressPage.SetProgress(0, 800);
  ProgressPage.Show;
  try
    Started := Exec(
      ExpandConstant('{app}\payload\flashserver-setup.exe'),
      '--backend wsl --bin-dir "' + ExpandConstant('{app}\payload') + '"' + WSLArgs +
        ' --progress-file "' + ProgressPath + '"',
      ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode);
    if not Started then
      SetupError := 'Could not start flashserver-setup.exe.'
    else
    begin
      Attempts := 0;
      LastStep := 0;
      LastText := '';
      LastLog := '';
      LastDone := False;
      while True do
      begin
        LoadProgress(ProgressPath, Step, Total, StepText, StepDone, HasDone,
          DoneCode, ProgressLog);
        if HasDone then
          Break;
        if (Step > 0) and (Total > 0) and
           ((Step <> LastStep) or (StepText <> LastText) or
            (StepDone <> LastDone) or (ProgressLog <> LastLog)) then
        begin
          Detail := 'Step ' + IntToStr(Step) + ' of ' + IntToStr(Total) + ': ' + StepText;
          if StepDone then
            Detail := Detail + ' (done)';
          if ProgressLog <> '' then
            ProgressPage.SetText(Detail, Copy(ProgressLog, 1, 160))
          else
            ProgressPage.SetText(Detail,
              'This can take several minutes on first install.');
          if StepDone then
            ProgressPage.SetProgress(Step * 100, Total * 100)
          else
            ProgressPage.SetProgress((Step - 1) * 100 + 50, Total * 100);
          LastStep := Step;
          LastText := StepText;
          LastDone := StepDone;
          LastLog := ProgressLog;
        end;
        Sleep(250);
        Inc(Attempts);
        if Attempts > 21600 then
        begin
          SetupError := 'Timed out after 90 minutes while waiting for setup.';
          Break;
        end;
      end;

      if SetupError = '' then
      begin
        if DoneCode = 3 then
        begin
          SetupReboot := True;
          ProgressPage.SetText('Restart required',
            'WSL2 was enabled. Restart Windows, then run Setup again.');
          ProgressPage.SetProgress(800, 800);
          Sleep(1500);
        end
        else if DoneCode <> 0 then
          SetupError := 'flashserver-setup.exe failed (exit code ' +
            IntToStr(DoneCode) + ').'
        else
        begin
          ProgressPage.SetText('Verifying the FlashServer environment',
            'Checking the systemd service and the local API...');
          ProgressPage.SetProgress(800, 800);
          Ready := VerifyReady;
          if Ready then
          begin
            ProgressPage.SetText('FlashServer is ready',
              'The service is active and http://localhost:8790/health responds.');
            ProgressPage.SetProgress(800, 800);
            Sleep(700);
            Result := True;
          end
          else
            SetupError := 'FlashServer was installed but did not become ready. ' +
              'The systemd service is not active or /health does not respond.';
        end;
      end;
    end;
  finally
    ProgressPage.Hide;
  end;

  if SetupReboot then
    MsgBox('WSL2 has been enabled, but Windows must be restarted before Ubuntu can be installed.' + #13#10#13#10 +
      'Restart the computer, then run FlashServer Setup again to finish the installation.',
      mbInformation, MB_OK)
  else if not Result then
  begin
    if SetupError = '' then
      SetupError := 'FlashServer setup did not complete.';
    SetupError := SetupError + #13#10#13#10 +
      'Log: ' + LogPath + #13#10#13#10 +
      'Last output:' + #13#10 + LogTail(LogPath, 1500);
    MsgBox(SetupError, mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetupOK := RunEnvironmentSetup;
end;

procedure InitializeWizard;
begin
  ProgressPage := CreateOutputProgressPage('Setting up FlashServer',
    'FlashServer runs inside WSL2. Setup installs Ubuntu and the resident service.');
  WSLDirPage := CreateInputDirPage(wpSelectDir,
    'WSL data directory',
    'Where should the Ubuntu virtual disk live?',
    'FlashServer runs inside WSL2. The Ubuntu disk holds model weights and runtimes, so choose a drive with at least 30 GB free. The default follows the installation drive; leave it unchanged to keep the WSL default.',
    False, '');
  WSLDirPage.Add('WSL data directory (leave empty for the WSL default):');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = WSLDirPage.ID then
  begin
    if Trim(WSLDirPage.Values[0]) = '' then
      WSLDirPage.Values[0] := ExtractFileDrive(WizardDirValue) + '\FlashServerWSL';
  end
  else if CurPageID = wpFinished then
  begin
    if SetupReboot then
      WizardForm.FinishedLabel.Caption :=
        'Windows must be restarted to finish enabling WSL2.' + #13#10 + #13#10 +
        'Restart the computer, then run FlashServer Setup again. The second run installs Ubuntu, ' +
        'the service, and verifies readiness.'
    else if SetupOK then
      WizardForm.FinishedLabel.Caption :=
        'FlashServer is installed and ready.' + #13#10 + #13#10 +
        'Environment: WSL2 + Ubuntu + systemd service (verified)' + #13#10 +
        'Health: ' + ClientAPIURL + '/health' + #13#10 +
        'API docs: ' + ClientAPIURL + '/docs'
    else
      WizardForm.FinishedLabel.Caption :=
        'FlashServer installation needs attention.' + #13#10 + #13#10 +
        'Check %USERPROFILE%\.flashcli\logs\setup.log and run the installer again.';
  end;
end;

[Messages]
WelcomeLabel2=This will install FlashServer, enable WSL2/Ubuntu when missing, and configure the resident model scheduler.%n%nAdministrator privileges and internet access are required. Enabling WSL2 may require one restart.
FinishedHeadingLabel=FlashServer Setup
FinishedLabel=FlashServer is installed and its service has been started.%n%nThe desktop client is opened automatically; API docs are at http://localhost:8790/docs.
