; ============================================================================
;  Aegis Planner - Windows installer (Inno Setup 6)
;  Build:  ISCC /DAppVersion=2.11.10 packaging\installer.iss   (after: pyinstaller packaging\aegis.spec)
;  build_windows.bat does all of this for you.
; ============================================================================
#ifndef AppVersion
  #define AppVersion "2.11.10"
#endif
#define AppName "Aegis Planner"
#define AppExe "AegisPlanner.exe"
#define AppPublisher "Aegis Planner"

[Setup]
AppId={{6B0B2C2E-5D0A-4C55-9B7C-AE615F1A0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
VersionInfoCompany={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; the user always gets to choose where to install
DisableDirPage=no
DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableReadyPage=no
UsePreviousAppDir=yes
OutputDir=..\installer_output
OutputBaseFilename=AegisPlanner-Setup-{#AppVersion}
SetupIconFile=..\aegis_desktop\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=installer_assets\wiz_164.bmp,installer_assets\wiz_246.bmp,installer_assets\wiz_328.bmp
WizardSmallImageFile=installer_assets\small_55.bmp,installer_assets\small_83.bmp,installer_assets\small_110.bmp
WizardImageStretch=no
InfoBeforeFile=installer_assets\privacy.txt
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; per-user install by default (no admin prompt); the wizard offers "for all users" as an option
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
AppMutex=AegisPlannerRunning
SetupMutex=AegisPlannerSetupMutex
ChangesAssociations=yes
CreateUninstallRegKey=yes
Uninstallable=yes
#ifdef SignTool
SignTool=aegissign
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
ConfirmUninstall=Remove %1 from this computer?

[CustomMessages]
english.ConfirmFallback=This removes %1, your encrypted vault, your settings and the log files from this computer.%n%nYour BACKUP folder is kept:%n%2%n%nRemove it now?
english.BackupsKept=%1 has been removed.%n%nYour backups were not touched. The default backup folder is:%n%2%n%n(If you chose another backup folder in Settings, it was not touched either.)

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startmenuicon"; Description: "Add to the &Start menu"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\AegisPlanner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\aegis_desktop\assets\aegis_file.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; the encrypted vault export gets its own document icon in Explorer (a page with the shield; the app opens files via its own Import dialog)
Root: HKA; Subkey: "Software\Classes\.aegis"; ValueType: string; ValueName: ""; ValueData: "AegisPlanner.Vault"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\AegisPlanner.Vault"; ValueType: string; ValueName: ""; ValueData: "Aegis encrypted vault"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\AegisPlanner.Vault\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\aegis_file.ico"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"; Parameters: "/SILENT /CONFIRM"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  ConfirmProceed = 0;
  ConfirmCancel = 3;

function DataDir(): String;
begin
  Result := ExpandConstant('{userappdata}') + '\AegisPlanner';
end;

function HasSwitch(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then
      Result := True;
end;

procedure DeleteFilesMatching(const Pattern: String);
var
  Rec: TFindRec;
  Dir: String;
begin
  Dir := ExtractFilePath(Pattern);
  if FindFirst(Pattern, Rec) then
  try
    repeat
      if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
        DeleteFile(Dir + Rec.Name);
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

procedure WipeDataFolder(const Dir: String);
begin
  // everything the program itself created, except the backup folder (and anything it did not create)
  DeleteFile(Dir + '\vault.aegis');
  DeleteFile(Dir + '\prefs.json');
  DeleteFile(Dir + '\app.lock');
  DeleteFilesMatching(Dir + '\aegis.log*');
  DeleteFilesMatching(Dir + '\*.tmp');
  RemoveDir(Dir);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root: Integer;
begin
  // Settings > Apps > Uninstall should open the branded confirmation screen and then remove quietly,
  // instead of a generic prompt: point the entry at the uninstaller with the switches that mean exactly that.
  // Inno Setup writes its own entry last, so this runs after it.
  if CurStep = ssDone then
  begin
    if IsAdminInstallMode() then
      Root := HKEY_LOCAL_MACHINE
    else
      Root := HKEY_CURRENT_USER;
    RegWriteStringValue(Root, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B0B2C2E-5D0A-4C55-9B7C-AE615F1A0001}_is1',
                        'UninstallString', '"' + ExpandConstant('{uninstallexe}') + '" /SILENT /CONFIRM');
  end;
end;

function ConfirmWanted(): Boolean;
begin
  // a person is at the keyboard: the plain uninstaller, or the /CONFIRM switch that Settings > Apps passes.
  // Scripted removal (/VERYSILENT, /SILENT alone) never shows a screen and never deletes data unless /PURGE is given
  Result := (not UninstallSilent()) or HasSwitch('/CONFIRM');
end;

function InitializeUninstall(): Boolean;
var
  Exe: String;
  Code: Integer;
begin
  Result := True;
  if not ConfirmWanted() then
    Exit;
  Exe := ExpandConstant('{app}\{#AppExe}');
  if FileExists(Exe) and Exec(Exe, '--uninstall-confirm --data-dir "' + DataDir() + '"', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code)
     and ((Code = ConfirmProceed) or (Code = ConfirmCancel)) then
    Result := (Code = ConfirmProceed)
  else
    // the branded screen could not run: a plain, honest confirmation instead (default answer: No)
    Result := MsgBox(FmtMessage(CustomMessage('ConfirmFallback'), ['{#AppName}', DataDir() + '\backups']),
                     mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // interactive: the person confirmed. Silent: the data stays, unless the caller says /PURGE.
  if ConfirmWanted() or HasSwitch('/PURGE') then
  begin
    WipeDataFolder(DataDir());
    if ConfirmWanted() then
      MsgBox(FmtMessage(CustomMessage('BackupsKept'), ['{#AppName}', DataDir() + '\backups']), mbInformation, MB_OK);
  end;
end;
