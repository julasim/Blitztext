; Blitztext – Inno Setup installer script
; Build:  iscc installer/blitztext.iss
; Requires that `pyinstaller build.spec` has been run first (produces dist/Blitztext/)
;
; NOTE: The AppId below is intentionally still the original "VOICETYPE00001" GUID.
; Keeping the AppId identical makes Inno Setup treat a fresh Blitztext install as
; an in-place upgrade of the existing VoiceType install — uninstalling VoiceType
; automatically and dropping Blitztext into its place. Do NOT change this GUID.

#define MyAppName        "Blitztext"
#define MyAppVersion     "1.0.14"
#define MyAppPublisher   "Julius Sima"
#define MyAppExeName     "Blitztext.exe"
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
OutputBaseFilename=Blitztext-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
; Close running Blitztext (and legacy VoiceType) before updating; we handle restart via [Run]
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\ui\assets\icon.ico

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Files]
Source: "..\dist\Blitztext\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
; Also kill any legacy VoiceType.exe still running from a pre-rename install.
; Fails silently if the process isn't running.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F"; Flags: runhidden; RunOnceId: "KillBlitztext"
Filename: "{cmd}"; Parameters: "/C taskkill /IM VoiceType.exe /F"; Flags: runhidden; RunOnceId: "KillLegacyVoiceType"

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
  LegacyAppData: string;
  ResultCode: Integer;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    AppData := ExpandConstant('{userappdata}\Blitztext');
    if DirExists(AppData) then
      DelTree(AppData, True, True, True);

    { Also wipe the pre-rename VoiceType folder in case migration hadn't run
      before the user uninstalled (e.g. upgrade-then-uninstall without ever
      launching the new app). }
    LegacyAppData := ExpandConstant('{userappdata}\VoiceType');
    if DirExists(LegacyAppData) then
      DelTree(LegacyAppData, True, True, True);

    { Delete all stored API keys from Windows Credential Manager.
      keyring's Windows backend stores the MOST RECENT entry with TargetName=<service>
      and older ones as TargetName=<username>@<service>. cmdkey exits silently if
      the entry doesn't exist, so listing all variants is safe. Includes both the
      new "Blitztext" service name and the legacy "VoiceType" one. }
    Exec(ExpandConstant('{cmd}'),
         '/C cmdkey /delete:Blitztext & ' +
         'cmdkey /delete:openai_api_key@Blitztext & ' +
         'cmdkey /delete:anthropic_api_key@Blitztext & ' +
         'cmdkey /delete:gemini_api_key@Blitztext & ' +
         'cmdkey /delete:openrouter_api_key@Blitztext & ' +
         'cmdkey /delete:ollama_api_key@Blitztext & ' +
         'cmdkey /delete:VoiceType & ' +
         'cmdkey /delete:openai_api_key@VoiceType & ' +
         'cmdkey /delete:anthropic_api_key@VoiceType & ' +
         'cmdkey /delete:gemini_api_key@VoiceType & ' +
         'cmdkey /delete:openrouter_api_key@VoiceType & ' +
         'cmdkey /delete:ollama_api_key@VoiceType',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

[Registry]
; Autostart entries (managed by the app itself via winreg, but clean up on uninstall).
; Both the new "Blitztext" value and the legacy "VoiceType" value are removed,
; so users who upgrade-then-uninstall don't leak a stale autostart.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: none; ValueName: "Blitztext"; Flags: dontcreatekey deletevalue uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: none; ValueName: "VoiceType"; Flags: dontcreatekey deletevalue uninsdeletevalue
