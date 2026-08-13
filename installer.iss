; SimBuilder installer (Inno Setup 6)
; Build chain (see build_installer.bat):
;   1. pyinstaller SimBuilder_dir.spec  -> build\installer_dist\SimBuilder\
;   2. iscc installer.iss               -> dist\SimBuilder-Setup.exe
;
; The one-DIR app launches instantly (no per-launch temp extraction) and
; trips fewer antivirus false-positives than the one-file exe. settings.json
; is created next to the exe on first run ({app}), so the app stays
; self-contained per machine; OneDrive-synced paths inside settings resolve
; on any signed-in machine.

#define MyAppName "SimBuilder"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "George Fares"
#define MyAppExeName "SimBuilder.exe"

[Setup]
AppId={{8F4C1B7E-2D5A-4E9C-9B1F-3A6D8C2E5F41}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; per-user install: no admin prompt, and {app} stays writable so
; settings.json can live next to the exe as the app expects
PrivilegesRequired=lowest
DefaultDirName={localappdata}\{#MyAppName}
OutputDir=dist
OutputBaseFilename=SimBuilder-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "build\installer_dist\SimBuilder\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; settings.json is created at runtime next to the exe; clean it up on uninstall
Type: files; Name: "{app}\settings.json"
