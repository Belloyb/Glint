; Inno Setup script for the Glint Windows installer.
;
; Build (on Windows, after `pyinstaller packaging\glint.spec`):
;     iscc packaging\windows-installer.iss
; ->  dist\installer\GlintSetup-<version>.exe
;
; NOTE: PyInstaller half of the pipeline is executed and validated on
; Linux; the installer itself is compiled/validated on real Windows
; hardware per docs/HARDWARE_VALIDATION.md §2.

#define MyAppName "Glint"
#define MyAppVersion "0.13.1"
#define MyAppPublisher "glint-player contributors"
#define MyAppExeName "Glint.exe"

[Setup]
; Stable upgrade identity: NEVER change this AppId across versions.
AppId={{A1C3E5F7-2B4D-4E6F-8A0C-5D7E9B1F3A5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Glint needs no admin rights: default to a per-user install (no UAC
; prompt). "PrivilegesRequired" must be EXPLICIT — Inno's default is
; "admin", which triggers the UsedUserAreasWarning because this script
; writes per-user HKCU file associations, and in admin mode those writes
; can land in the elevating account's profile instead of the user's.
PrivilegesRequired=lowest
; The user may still choose an all-users install (Program Files, UAC) —
; {autopf} follows that choice automatically.
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=GlintSetup-{#MyAppVersion}
SetupIconFile=..\app\assets\icons\app.ico
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; The application is GPL-3.0-or-later; the installer shows the licence.
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "fileassoc"; Description: "Associate common media files with Glint"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
; The PyInstaller onedir output (Glint.exe, Qt runtime, icons, and the
; bundled libmpv-2.dll when it was in the repository root at build time).
Source: "..\dist\Glint\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; Licence texts that must accompany the binaries (docs/REDISTRIBUTION.md).
Source: "..\LICENSE"; DestDir: "{app}\doc"; Flags: ignoreversion
Source: "..\docs\REDISTRIBUTION.md"; DestDir: "{app}\doc"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; File associations (optional task). Each extension points to Glint.exe.
Root: HKCU; Subkey: "Software\Classes\Glint.MediaFile"; ValueType: string; ValueName: ""; ValueData: "Glint media file"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Glint.MediaFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\Glint.MediaFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
; Per-extension association lines (plain [Registry] entries, no macro):
#include "assoc-extensions.iss.inc"

; --- Default-apps registration (v0.13.1) ---------------------------------
; Makes Glint APPEAR in Settings > Apps > Default apps and in the
; "Open with" candidates, so users can set it as their default player
; the Windows-blessed way. Purely a listing — nothing is claimed until
; the user picks Glint in Settings; registered regardless of the optional
; fileassoc task above.
Root: HKCU; Subkey: "Software\Glint\Capabilities"; ValueType: string; ValueName: ""; ValueData: "Glint media player"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Glint\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Glint - a free, open-source media player"
Root: HKCU; Subkey: "Software\Glint\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\Glint.exe,0"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mkv"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp4"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4v"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mov"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".avi"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".webm"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wmv"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flv"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ts"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp3"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flac"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ogg"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".opus"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wav"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4a"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aac"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\Glint\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u8"; ValueData: "Glint.MediaFile"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Glint"; ValueData: "Software\Glint\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function VulkanRuntimePresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\vulkan-1.dll'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Current libmpv builds import vulkan-1.dll; machines without the Vulkan
  // runtime cannot start the engine. Warn (don't block) with the official
  // source — Glint's --check names the exact dependency if it bites later.
  if (CurStep = ssPostInstall) and not VulkanRuntimePresent() then
  begin
    MsgBox(
      'Note: the Vulkan runtime (vulkan-1.dll) was not found on this ' +
      'computer. Glint''s media engine needs it, so video playback will ' +
      'not start until it is installed.' + #13#10#13#10 +
      'Fix: install the official Vulkan Runtime from ' +
      'https://vulkan.lunarg.com/sdk/home (Windows x64 "Runtime Installer"), ' +
      'or update your GPU driver, then run "Glint --check" to verify.',
      mbInformation, MB_OK);
  end;
end;

[UninstallDelete]
; User settings and logs in %APPDATA% are deliberately NOT removed.
Type: filesandordirs; Name: "{app}"
