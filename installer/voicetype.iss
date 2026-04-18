; VoiceType – Inno Setup installer script
; Build:  iscc installer/voicetype.iss
; Requires that `pyinstaller build.spec` has been run first (produces dist/VoiceType/)

#define MyAppName        "VoiceType"
#define MyAppVersion     "1.0.10"
#define MyAppPublisher   "Julius Sima"
#define MyAppExeName     "VoiceType.exe"
#define MyAppId          "{{B2FC3A41-7D58-4F82-9F3A-VOICETYPE00001}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=..\dist-installer
OutputBaseFilename=VoiceType-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
; Close running VoiceType before updating; we handle restart via [Run]
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\ui\assets\icon.ico

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Files]
Source: "..\dist\VoiceType\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; After install (including silent re-install during update), launch the new app.
; No `skipifsilent` = runs even in /VERYSILENT mode → auto-restart after update.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall

[UninstallRun]
; Gracefully stop the running app before we start removing files.
; Fails silently if app isn't running.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F"; Flags: runhidden; RunOnceId: "KillVoiceType"

[Code]
{ --- Ask at uninstall: also remove user data (Whisper model, config, keys)? --- }

var
  RemoveUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  RemoveUserData := MsgBox(
    'Sollen auch alle Benutzerdaten entfernt werden?' + #13#10 + #13#10 +
    '• Whisper-Sprachmodell (~1,5 GB)' + #13#10 +
    '• Einstellungen' + #13#10 + #13#10 +
    'Die API-Keys im Windows-Anmeldeinformationsmanager werden ebenfalls gelöscht.' + #13#10 + #13#10 +
    'Bei "Nein" bleiben die Daten erhalten (z.B. für Neuinstallation).',
    mbConfirmation, MB_YESNO) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppData: string;
  ResultCode: Integer;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    AppData := ExpandConstant('{userappdata}\VoiceType');
    if DirExists(AppData) then
      DelTree(AppData, True, True, True);

    { Delete all stored API keys from Windows Credential Manager.
      keyring's Windows backend stores the MOST RECENT entry with TargetName=VoiceType
      and older ones as TargetName=<username>@VoiceType.
      cmdkey exits silently if the entry doesn't exist, so listing all variants is safe. }
    Exec(ExpandConstant('{cmd}'),
         '/C cmdkey /delete:VoiceType & ' +
         'cmdkey /delete:openai_api_key@VoiceType & ' +
         'cmdkey /delete:anthropic_api_key@VoiceType & ' +
         'cmdkey /delete:gemini_api_key@VoiceType & ' +
         'cmdkey /delete:openrouter_api_key@VoiceType & ' +
         'cmdkey /delete:ollama_api_key@VoiceType',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

[Registry]
; Autostart entry (managed by the app itself via winreg, but clean up on uninstall)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: none; ValueName: "VoiceType"; Flags: dontcreatekey deletevalue uninsdeletevalue
