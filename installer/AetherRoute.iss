#ifndef SourceRoot
  #error SourceRoot must point to the complete frozen AetherRoute folder.
#endif
#ifndef OutputRoot
  #error OutputRoot must point to the release output folder.
#endif
#ifndef AppVersion
  #error AppVersion is required.
#endif

[Setup]
AppId={{8D0EAC88-C58B-4EBD-9372-25CA5D01AF9C}
AppName=AetherRoute
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AetherRoute
DefaultGroupName=AetherRoute
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputRoot}
OutputBaseFilename=AetherRoute-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AetherRoute.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AetherRoute"; Filename: "{app}\AetherRoute.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AetherRoute"; Filename: "{app}\AetherRoute.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AetherRoute.exe"; Description: "Open AetherRoute"; Flags: nowait postinstall skipifsilent

; Saved data is outside {app}, under LOCALAPPDATA\Aion2RouteSync.
; Do not add UninstallDelete entries for that directory.
