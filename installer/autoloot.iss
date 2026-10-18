; Build with tools/build_installer.py. End users need only the resulting EXE.
#ifndef PayloadDir
  #error PayloadDir must point to a qualified standalone payload
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#ifdef Audit
  #define AppIdentity "BetterAutoLoot-Isolated-Audit"
  #define AppTitle "Better AutoLoot Audit"
  #define OutputName "BetterAutoLoot-Audit-Setup"
#else
  #define AppIdentity "BetterAutoLoot-DLTB"
  #define AppTitle "Better AutoLoot"
  #define OutputName "BetterAutoLoot-Setup-" + AppVersion
#endif

[Setup]
AppId={#AppIdentity}
AppName={#AppTitle}
AppVersion={#AppVersion}
AppPublisher=Rhadamanthe1
AppPublisherURL=https://github.com/Rhadamanthe0/dying-light-the-beast-autoloot
DefaultDirName={localappdata}\Programs\{#AppTitle}
DefaultGroupName={#AppTitle}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=no
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
UninstallDisplayName={#AppTitle}
UninstallDisplayIcon={app}\runtime\pythonw.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#PayloadDir}\tools\manage.ps1"; Flags: dontcopy
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Pause AutoLoot"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\tools\control.py"" Pause"; WorkingDir: "{app}"; Check: ActivationEnabled
Name: "{group}\Resume AutoLoot"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\tools\control.py"" Resume"; WorkingDir: "{app}"; Check: ActivationEnabled
Name: "{group}\Uninstall Better AutoLoot"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\evidence"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\tools"
Type: files; Name: "{app}\autoloot.local.json"
Type: files; Name: "{app}\.autoloot-owned"
Type: files; Name: "{app}\.autoloot-disabled"
Type: dirifempty; Name: "{app}"

[Code]
var
  NoAutoStart: Boolean;
  StatePath: String;

function ActivationEnabled: Boolean;
begin
  Result := not NoAutoStart;
end;

function PowerShellPath: String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

function RunLifecycle(ScriptPath, Action, Extra: String): Boolean;
var
  ExitCode: Integer;
  Arguments: String;
begin
  Arguments := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ScriptPath + '" -Action ' + Action + ' -Root "' + ExpandConstant('{app}') + '"' + Extra;
  if NoAutoStart then Arguments := Arguments + ' -NoAutoStart';
  Result := Exec(PowerShellPath, Arguments, ExpandConstant('{tmp}'), SW_HIDE,
    ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
end;

function InitializeSetup: Boolean;
var
  I: Integer;
begin
  NoAutoStart := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOAUTOSTART') = 0 then NoAutoStart := True;
#ifdef Audit
  NoAutoStart := True;
#endif
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Entry: TFindRec;
  Owned: AnsiString;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}')) then begin
    if FileExists(ExpandConstant('{app}\.autoloot-owned')) then begin
      if not LoadStringFromFile(ExpandConstant('{app}\.autoloot-owned'), Owned) or
        (Owned <> 'BetterAutoLoot-DLTB-v1') then begin
        Result := 'This folder is not a recognized Better AutoLoot installation.';
        exit;
      end;
      if FileExists(ExpandConstant('{app}\.autoloot-disabled')) then NoAutoStart := True;
    end else if FindFirst(ExpandConstant('{app}\*'), Entry) then begin
      try
        repeat
          if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
            Result := 'Choose an empty, dedicated folder for Better AutoLoot.';
            exit;
          end;
        until not FindNext(Entry);
      finally
        FindClose(Entry);
      end;
    end;
  end;
  if not ForceDirectories(ExpandConstant('{app}')) or
    not SaveStringToFile(ExpandConstant('{app}\.autoloot-owned'), 'BetterAutoLoot-DLTB-v1', False) then begin
    Result := 'The installation folder could not be created.';
    exit;
  end;
  if NoAutoStart then
    if not SaveStringToFile(ExpandConstant('{app}\.autoloot-disabled'), 'manual activation', False) then begin
      Result := 'The installation mode could not be saved.';
      exit;
    end;
  ExtractTemporaryFile('manage.ps1');
  StatePath := ExpandConstant('{tmp}\autoloot-update.json');
  if not RunLifecycle(ExpandConstant('{tmp}\manage.ps1'), 'Prepare',
    ' -StatePath "' + StatePath + '"') then
    Result := 'AutoLoot could not stop safely. See the Prepare-AutoLoot.log in the installation folder.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Running offline checks. This may take a few minutes...';
    if not RunLifecycle(ExpandConstant('{app}\tools\manage.ps1'), 'Configure',
      ' -StatePath "' + StatePath + '"') then
      RaiseException('AutoLoot setup failed. See evidence\Configure-AutoLoot.log in the installation folder.');
  end;
end;

function InitializeUninstall: Boolean;
var
  Owned: AnsiString;
begin
  NoAutoStart := FileExists(ExpandConstant('{app}\.autoloot-disabled'));
  Result := LoadStringFromFile(ExpandConstant('{app}\.autoloot-owned'), Owned);
  if Result then Result := Owned = 'BetterAutoLoot-DLTB-v1';
  if not Result then
    SuppressibleMsgBox('This folder is not a recognized Better AutoLoot installation.', mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if not RunLifecycle(ExpandConstant('{app}\tools\manage.ps1'), 'Uninstall', '') then
      RaiseException('AutoLoot could not stop safely. Wait and retry uninstalling. No running process was forced to close.');
  end;
end;
