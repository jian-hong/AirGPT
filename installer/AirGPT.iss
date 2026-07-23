; AirGPT Setup — Inno Setup
; Build: 1) build_exe.bat  2) (optional) copy Netie Space publish into dist\bundle\NetieSpace
;        3) ISCC.exe installer\AirGPT.iss
; Output: dist\installer\AirGPT-Setup.exe
;
; Default: AirGPT + Netie Space (when Space files are present under dist\bundle\NetieSpace).

#define MyAppName "AirGPT"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Netie"
#define MyAppExeName "AirGPT.exe"
#define MySpaceExeName "NetieSpace.exe"

[Setup]
AppId={{B7E2D4A1-8C3F-4A90-9E1B-AIRGPT-NETIE01}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://netie.ai/
AppSupportURL=https://netie.ai/contact/
DefaultDirName={autopf}\AirGPT
DefaultGroupName=AirGPT
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=AirGPT-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=legal\terms.txt
InfoBeforeFile=legal\privacy-summary.txt
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"
Name: "startup"; Description: "Start AirGPT with Windows"; GroupDescription: "Startup:"
Name: "copilot"; Description: "Let the Copilot key open AirGPT (optional)"; GroupDescription: "Keyboard:"; Flags: unchecked
Name: "hotkey"; Description: "Enable Win+Alt+Space to open AirGPT Quick"; GroupDescription: "Keyboard:"
Name: "installspace"; Description: "Install Netie Space together with AirGPT (recommended)"; GroupDescription: "Bundle:"; Flags: checkedonce

[Files]
; AirGPT onedir build
Source: "..\dist\AirGPT\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Legal copies for About menu
Source: "legal\*"; DestDir: "{app}\legal"; Flags: ignoreversion
; Netie Space — only if publish output exists
Source: "..\dist\bundle\NetieSpace\*"; DestDir: "{app}\NetieSpace"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Tasks: installspace

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Netie Space"; Filename: "{app}\NetieSpace\{#MySpaceExeName}"; Tasks: installspace
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autodesktop}\Netie Space"; Filename: "{app}\NetieSpace\{#MySpaceExeName}"; Tasks: desktopicon installspace

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AirGPT"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup
; Protocol handler for shared Netie deep links
Root: HKCU; Subkey: "Software\Classes\airgpt"; ValueType: string; ValueName: ""; ValueData: "URL:AirGPT Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\airgpt"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\airgpt\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
; Launcher flags written for tray helper (future)
Root: HKCU; Subkey: "Software\Netie\AirGPT"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Netie\AirGPT"; ValueType: dword; ValueName: "CopilotRemap"; ValueData: "1"; Tasks: copilot
Root: HKCU; Subkey: "Software\Netie\AirGPT"; ValueType: dword; ValueName: "GlobalHotkey"; ValueData: "1"; Tasks: hotkey
Root: HKCU; Subkey: "Software\Netie\AirGPT"; ValueType: string; ValueName: "Hotkey"; ValueData: "Win+Alt+Space"; Tasks: hotkey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AirGPT"; Flags: nowait postinstall skipifsilent
Filename: "{app}\NetieSpace\{#MySpaceExeName}"; Description: "Launch Netie Space"; Flags: nowait postinstall skipifsilent skipifdoesntexist; Tasks: installspace

[Code]
function InitializeWizard(): Boolean;
begin
  Result := True;
  WizardForm.LicenseAcceptedRadio.Checked := False;
end;
