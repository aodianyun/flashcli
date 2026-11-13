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
const
  CrLf = #13#10;

var
  PurgeModels: Boolean;
  RemoveCLI: Boolean;
  PurgeSettings: Boolean;
  PurgeDistro: Boolean;
  SetupOK: Boolean;
  SetupReboot: Boolean;
  SetupError: String;
  ProgressPage: TOutputProgressWizardPage;
  ProgressCancelButton: TNewButton;
  ProgressCancelled: Boolean;
  SetupRunning: Boolean;
  WSLDirPage: TInputDirWizardPage;
  UninstallForm: TSetupForm;
  CbAll, CbModels, CbCli, CbSettings, CbDistro: TCheckBox;

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
  if PurgeDistro then
    Result := Result + ' --purge-distro';
end;

procedure ProgressCancelClick(Sender: TObject);
begin
  ProgressCancelled := True;
end;

{ Keep the progress bar and Cancel button on the bottom row, right-aligned. }
procedure LayoutProgressPage;
begin
  ProgressPage.ProgressBar.Top :=
    ProgressPage.Msg1Label.Parent.Height - ProgressPage.ProgressBar.Height - ScaleY(16);
  ProgressPage.ProgressBar.Width :=
    ProgressPage.Msg1Label.Width - ProgressCancelButton.Width - ScaleX(24);
  ProgressCancelButton.Left :=
    ProgressPage.ProgressBar.Left + ProgressPage.ProgressBar.Width + ScaleX(12);
  ProgressCancelButton.Top := ProgressPage.ProgressBar.Top +
    (ProgressPage.ProgressBar.Height - ProgressCancelButton.Height) div 2;
end;

// Removing the distro already removes the model cache and the CLI inside it,
// so those options are forced on and disabled.
procedure SyncDistroDependent;
begin
  CbModels.Enabled := not CbDistro.Checked;
  CbCli.Enabled := not CbDistro.Checked;
  if CbDistro.Checked then
  begin
    CbModels.Checked := True;
    CbCli.Checked := True;
  end;
end;

procedure DistroOptionClick(Sender: TObject);
begin
  SyncDistroDependent;
end;

procedure SelectAllClick(Sender: TObject);
begin
  CbModels.Checked := CbAll.Checked;
  CbCli.Checked := CbAll.Checked;
  CbSettings.Checked := CbAll.Checked;
  CbDistro.Checked := CbAll.Checked;
  SyncDistroDependent;
end;

// The Inno uninstaller has no wizard pages, so show a small custom form with
// the optional cleanup choices. Defaults keep all data.
procedure ShowUninstallOptions;
var
  Title: TNewStaticText;
  Btn: TButton;
begin
  UninstallForm := CreateCustomForm();
  try
    UninstallForm.Caption := 'FlashServer 卸载选项';
    UninstallForm.ClientWidth := ScaleX(540);
    UninstallForm.ClientHeight := ScaleY(304);
    UninstallForm.Position := poScreenCenter;
    UninstallForm.BorderStyle := bsDialog;

    Title := TNewStaticText.Create(UninstallForm);
    Title.Parent := UninstallForm;
    Title.Left := ScaleX(16);
    Title.Top := ScaleY(14);
    Title.Width := ScaleX(508);
    Title.Caption := '默认保留模型缓存和设置。勾选以下项目会在卸载时一并删除：';

    CbAll := TCheckBox.Create(UninstallForm);
    CbAll.Parent := UninstallForm;
    CbAll.Left := ScaleX(16);
    CbAll.Top := ScaleY(46);
    CbAll.Width := ScaleX(508);
    CbAll.Caption := '全选（删除所有 FlashServer 数据）';
    CbAll.Checked := False;
    CbAll.OnClick := @SelectAllClick;

    CbModels := TCheckBox.Create(UninstallForm);
    CbModels.Parent := UninstallForm;
    CbModels.Left := ScaleX(16);
    CbModels.Top := ScaleY(80);
    CbModels.Width := ScaleX(508);
    CbModels.Caption := '模型缓存、权重和运行环境（~/.flashcli，不可恢复）';
    CbModels.Checked := False;

    CbCli := TCheckBox.Create(UninstallForm);
    CbCli.Parent := UninstallForm;
    CbCli.Left := ScaleX(16);
    CbCli.Top := ScaleY(114);
    CbCli.Width := ScaleX(508);
    CbCli.Caption := 'flashcli 命令行（/usr/local/bin/flashcli）';
    CbCli.Checked := False;

    CbSettings := TCheckBox.Create(UninstallForm);
    CbSettings.Parent := UninstallForm;
    CbSettings.Left := ScaleX(16);
    CbSettings.Top := ScaleY(148);
    CbSettings.Width := ScaleX(508);
    CbSettings.Caption := '客户端设置（%LOCALAPPDATA%\FlashServer）';
    CbSettings.Checked := False;

    CbDistro := TCheckBox.Create(UninstallForm);
    CbDistro.Parent := UninstallForm;
    CbDistro.Left := ScaleX(16);
    CbDistro.Top := ScaleY(182);
    CbDistro.Width := ScaleX(508);
    CbDistro.Caption := '删除 Ubuntu 发行版及虚拟磁盘（释放 VHDX 空间，Ubuntu 内所有数据丢失）';
    CbDistro.Checked := False;
    CbDistro.OnClick := @DistroOptionClick;
    SyncDistroDependent;

    Btn := TButton.Create(UninstallForm);
    Btn.Parent := UninstallForm;
    Btn.Caption := '继续卸载';
    Btn.ModalResult := mrOk;
    Btn.Default := True;
    Btn.Left := ScaleX(408);
    Btn.Top := ScaleY(254);
    Btn.Width := ScaleX(116);
    Btn.Height := ScaleY(30);

    UninstallForm.ShowModal;
    PurgeModels := CbModels.Checked;
    RemoveCLI := CbCli.Checked;
    PurgeSettings := CbSettings.Checked;
    PurgeDistro := CbDistro.Checked;
  finally
    UninstallForm.Free;
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
        'See ' + ExpandConstant('{localappdata}') + '\FlashServer\logs\setup.log.', mbError, MB_OK);
  end
  else if (CurUninstallStep = usPostUninstall) and PurgeSettings then
  begin
    // Setup has exited by now, so its setup.log is closed and the Windows-side
    // client state can go. Model caches (~/.flashcli) are controlled by
    // --purge-models and must not be removed here.
    if GetEnv('LOCALAPPDATA') <> '' then
      DelTree(GetEnv('LOCALAPPDATA') + '\FlashServer', True, True, True);
  end;
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

{ Keeps only printable ASCII. Windows tools such as wsl.exe emit UTF-16LE,
  which would otherwise show up as spaced-out garbage in the log view. }
function CleanProgressLine(const Value: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(Value) do
  begin
    C := Value[I];
    if (C >= ' ') and (C <= '~') then
      Result := Result + C;
  end;
  Result := Trim(Result);
end;

function IsProgressNoise(const Value: String): Boolean;
begin
  Result := (Value = '') or (Copy(Value, 1, 17) = 'flashserver-setup') or
    (Copy(Value, 1, 7) = 'System:') or (Copy(Value, 1, 4) = 'Log:') or
    (Copy(Value, 1, 15) = 'Windows must be') or (Copy(Value, 1, 5) = 'DONE ');
end;

{ Returns the last MaxLines useful lines of the progress file. }
procedure AddProgressLine(Lines: TStringList; const Raw: String; MaxLines: Integer);
var
  T: String;
begin
  T := CleanProgressLine(Raw);
  if IsProgressNoise(T) then
    Exit;
  if Length(T) > 120 then
    T := Copy(T, 1, 117) + '...';
  Lines.Add(T);
  while Lines.Count > MaxLines do
    Lines.Delete(0);
end;

{ Returns the last MaxLines useful lines of the progress file. }
function ProgressTail(const S: String; MaxLines: Integer): String;
var
  I, StartPos: Integer;
  Lines: TStringList;
begin
  Lines := TStringList.Create;
  try
    StartPos := 1;
    for I := 1 to Length(S) do
    begin
      if (S[I] = #10) or (S[I] = #13) then
      begin
        AddProgressLine(Lines, Copy(S, StartPos, I - StartPos), MaxLines);
        StartPos := I + 1;
      end;
    end;
    AddProgressLine(Lines, Copy(S, StartPos, Length(S) - StartPos + 1), MaxLines);
    Result := Lines.Text;
  finally
    Lines.Free;
  end;
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
          if (Length(StepText) >= 4) and
             (Copy(StepText, Length(StepText) - 3, 4) = ' ...') then
            StepText := TrimRight(Copy(StepText, 1, Length(StepText) - 4));
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
  var DoneCode: Integer; var LogText: String): Boolean;
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
  LogText := '';
  Result := LoadStringFromFile(Path, A);
  if Result then
  begin
    S := A;
    ParseProgress(S, Step, Total, StepText, StepDone, HasDone, DoneCode);
    LogText := ProgressTail(S, 7);
  end;
end;

function Utf8ToUnicode(const A: AnsiString): String;
var
  I, N, CP: Integer;
  B: Byte;
begin
  Result := '';
  I := 1;
  N := Length(A);
  while I <= N do
  begin
    B := Ord(A[I]);
    if B < $80 then
    begin
      CP := B;
      Inc(I);
    end
    else if (B and $E0) = $C0 then
    begin
      CP := (B and $1F) shl 6;
      Inc(I);
      if I <= N then begin CP := CP or (Ord(A[I]) and $3F); Inc(I); end;
    end
    else if (B and $F0) = $E0 then
    begin
      CP := (B and $0F) shl 12;
      Inc(I);
      if I <= N then begin CP := CP or ((Ord(A[I]) and $3F) shl 6); Inc(I); end;
      if I <= N then begin CP := CP or (Ord(A[I]) and $3F); Inc(I); end;
    end
    else if (B and $F8) = $F0 then
    begin
      CP := (B and $07) shl 18;
      Inc(I);
      if I <= N then begin CP := CP or ((Ord(A[I]) and $3F) shl 12); Inc(I); end;
      if I <= N then begin CP := CP or ((Ord(A[I]) and $3F) shl 6); Inc(I); end;
      if I <= N then begin CP := CP or (Ord(A[I]) and $3F); Inc(I); end;
    end
    else
    begin
      Inc(I);
      Continue;
    end;
    if CP <= $FFFF then
      Result := Result + Chr(CP)
    else if CP <= $10FFFF then
    begin
      CP := CP - $10000;
      Result := Result + Chr($D800 + (CP shr 10)) + Chr($DC00 + (CP and $3FF));
    end;
  end;
end;

function CleanAsciiLog(const Value: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(Value) do
  begin
    C := Value[I];
    if (C = #13) or (C = #10) or (C = #9) or ((C >= ' ') and (C <= '~')) then
      Result := Result + C;
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
    S := CleanAsciiLog(A);
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

function WSLDistroName: String;
var
  A: AnsiString;
  S: String;
begin
  Result := 'Ubuntu';
  if LoadStringFromFile(ExpandConstant('{localappdata}') + '\FlashServer\distro.txt', A) then
  begin
    S := Trim(String(A));
    if S <> '' then
      Result := S;
  end;
end;

function RunEnvironmentSetup: Boolean;
var
  ResultCode, Step, Total, DoneCode, Attempts: Integer;
  StepText, Detail, ProgressPath, LogPath, ProgressLog, LastLog: String;
  StepDone, HasDone, Started, LastDone: Boolean;
  LastStep: Integer;
  LastText: String;
  WSLArgs: String;
  Elapsed, LastElapsed: Integer;
begin
  Result := False;
  SetupError := '';
  SetupReboot := False;
  SetupRunning := False;
  ProgressCancelled := False;
  LastElapsed := -1;
  ProgressPath := ExpandConstant('{tmp}\flashserver-progress.txt');
  LogPath := ExpandConstant('{localappdata}') + '\FlashServer\logs\setup.log';
  DeleteFile(ProgressPath);
  WSLArgs := '';
  if Trim(WSLDirPage.Values[0]) <> '' then
    WSLArgs := ' --wsl-dir "' + WSLDirPage.Values[0] + '"';

  ProgressPage.Msg1Label.Caption :=
    'Preparing the FlashServer environment' + #13#10#13#10 +
    'Checking WSL2 and Ubuntu. On a new PC this can take several minutes.';
  ProgressPage.Msg2Label.Visible := False;
  ProgressPage.SetProgress(0, 800);
  ProgressPage.Show;
  LayoutProgressPage;
  ProgressCancelButton.Visible := True;
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
      SetupRunning := True;
      Attempts := 0;
      LastStep := 0;
      LastText := '';
      LastLog := '';
      LastDone := False;
      while True do
      begin
        LoadProgress(ProgressPath, Step, Total, StepText, StepDone, HasDone,
          DoneCode, ProgressLog);
        if ProgressCancelled then
        begin
          SetupError := 'Setup was cancelled.';
          Exec(ExpandConstant('{sys}\taskkill.exe'),
            '/F /T /IM flashserver-setup.exe', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode);
          SetupRunning := False;
          Break;
        end;
        if HasDone then
          Break;
        Elapsed := Attempts div 4;
        if (Step > 0) and (Total > 0) then
        begin
          if (Step <> LastStep) or (StepText <> LastText) or
             (StepDone <> LastDone) or (ProgressLog <> LastLog) or
             (Elapsed <> LastElapsed) then
          begin
            Detail := 'Step ' + IntToStr(Step) + ' of ' + IntToStr(Total) + ': ' + StepText;
            if StepDone then
              Detail := Detail + ' (done)'
            else
              Detail := Detail + ' (' + IntToStr(Elapsed) + 's)';
            if ProgressLog <> '' then
              ProgressPage.Msg1Label.Caption := Detail + #13#10#13#10 + ProgressLog
            else
              ProgressPage.Msg1Label.Caption := Detail + #13#10#13#10 +
                'This can take several minutes on first install.';
            LastStep := Step;
            LastText := StepText;
            LastDone := StepDone;
            LastLog := ProgressLog;
            LastElapsed := Elapsed;
          end;
          if StepDone then
            ProgressPage.SetProgress(Step * 100, Total * 100)
          else
            ProgressPage.SetProgress((Step - 1) * 100 + 50, Total * 100);
        end
        else if Elapsed <> LastElapsed then
        begin
          ProgressPage.Msg1Label.Caption :=
            'Preparing the FlashServer environment (' + IntToStr(Elapsed) + 's)' + CrLf +
            CrLf + 'Starting the setup engine...' + CrLf +
            'Log: ' + LogPath;
          ProgressPage.SetProgress(0, 800);
          LastElapsed := Elapsed;
        end;
        Sleep(250);
        Inc(Attempts);
        if Attempts > 21600 then
        begin
          SetupError := 'Timed out after 90 minutes while waiting for setup.';
          Break;
        end;
      end;
      if HasDone then
        SetupRunning := False;

      if SetupError = '' then
      begin
        if DoneCode = 3 then
        begin
          SetupReboot := True;
          ProgressPage.Msg1Label.Caption := 'Restart required' + #13#10#13#10 +
            'WSL2 was enabled. Restart Windows, then run Setup again.';
          ProgressPage.SetProgress(800, 800);
          Sleep(1500);
        end
        else if DoneCode <> 0 then
          SetupError := 'flashserver-setup.exe failed (exit code ' +
            IntToStr(DoneCode) + ').'
        else
        begin
          ProgressPage.Msg1Label.Caption := 'Verifying the FlashServer environment' +
            CrLf + CrLf + 'Checking the systemd service and the local API...';
          ProgressPage.SetProgress(800, 800);
          // The setup engine already waited for systemd and /health and printed
          // DONE 0. Do not repeat the WSL check from the 32-bit installer:
          // sysnative/WSL resolution can produce a false negative.
          Sleep(500);
          ProgressPage.Msg1Label.Caption := 'FlashServer is ready' + #13#10#13#10 +
            'The service is active and the local API responded during setup.';
          ProgressPage.SetProgress(800, 800);
          Sleep(700);
          Result := True;
        end;
      end;
    end;
  finally
    ProgressCancelButton.Visible := False;
    ProgressPage.Hide;
  end;

  if ProgressCancelled then
    Abort;
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
      'Last output (ASCII only; see setup.log for full text):' + #13#10 + LogTail(LogPath, 1500);
    MsgBox(SetupError, mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetupOK := RunEnvironmentSetup;
end;

{ Kill the setup engine if the wizard is closed or cancelled while it runs. }
procedure DeinitializeSetup;
var
  ResultCode: Integer;
begin
  if SetupRunning then
    Exec(ExpandConstant('{sys}\taskkill.exe'),
      '/F /T /IM flashserver-setup.exe', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
end;

procedure InitializeWizard;
begin
  ProgressPage := CreateOutputProgressPage('Setting up FlashServer',
    'FlashServer runs inside WSL2. Setup installs Ubuntu and the resident service.');
  { The stock output page has two one-line labels. Turn the first one into a
    multi-line log view and move the progress bar below it. }
  ProgressPage.Msg1Label.AutoSize := False;
  ProgressPage.Msg1Label.WordWrap := True;
  ProgressPage.Msg1Label.Height := ScaleY(170);
  ProgressPage.Msg2Label.Visible := False;
  ProgressPage.ProgressBar.Top := ScaleY(178);

  ProgressCancelButton := TNewButton.Create(WizardForm);
  ProgressCancelButton.Parent := ProgressPage.Msg1Label.Parent;
  ProgressCancelButton.Caption := 'Cancel';
  ProgressCancelButton.Width := ScaleX(88);
  ProgressCancelButton.Height := ScaleY(26);
  ProgressCancelButton.OnClick := @ProgressCancelClick;
  ProgressCancelButton.Visible := False;
  LayoutProgressPage;

  WSLDirPage := CreateInputDirPage(wpSelectDir,
    'WSL data directory',
    'Where should the Ubuntu virtual disk live?',
    'FlashServer runs inside WSL2. The Ubuntu disk holds model weights and runtimes, so choose a drive with at least 30 GB free. The default is a sibling of the installation directory (FlashServerWSL), or %LOCALAPPDATA%\FlashServerWSL when installing under Program Files; leave it empty to keep the WSL default.',
    False, '');
  WSLDirPage.Add('WSL data directory (leave empty for the WSL default):');
end;

function DefaultWSLDir: String;
var
  Base: String;
begin
  Base := AddBackslash(ExtractFileDir(WizardDirValue));
  if Pos('\PROGRAM FILES', Uppercase(Base)) > 0 then
    Result := ExpandConstant('{localappdata}') + '\FlashServerWSL'
  else
    Result := Base + 'FlashServerWSL';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = WSLDirPage.ID then
  begin
    if Trim(WSLDirPage.Values[0]) = '' then
      WSLDirPage.Values[0] := DefaultWSLDir;
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
        'Check ' + ExpandConstant('{localappdata}') + '\FlashServer\logs\setup.log and run the installer again.';
  end;
end;

[Messages]
WelcomeLabel2=This will install FlashServer, enable WSL2/Ubuntu when missing, and configure the resident model scheduler.%n%nAdministrator privileges and internet access are required. Enabling WSL2 may require one restart.
FinishedHeadingLabel=FlashServer Setup
FinishedLabel=FlashServer is installed and its service has been started.%n%nThe desktop client is opened automatically; API docs are at http://localhost:8790/docs.
