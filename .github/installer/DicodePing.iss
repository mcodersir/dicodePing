#define MyAppName "DicodePing"
#ifndef MyAppVersion
#define MyAppVersion "4.9.8"
#endif
#define MyAppPublisher "DicodePing"
#define MyAppExeName "DicodePing.exe"

[Setup]
AppId={{4B2D3F4A-2204-4F7C-B2C0-7B6606B587B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DicodePing
DefaultGroupName=DicodePing
OutputDir=..\..\dist
OutputBaseFilename=DicodePing-{#MyAppVersion}-windows-x64-installer
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\apps\desktop\v2rayN.Desktop\Assets\DicodePing.ico

[Files]
Source: "..\..\publish\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\DicodePing"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\DicodePing"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch DicodePing"; Flags: nowait postinstall skipifsilent shellexec; Verb: "runas"
