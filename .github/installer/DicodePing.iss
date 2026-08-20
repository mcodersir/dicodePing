#define MyAppName "DicodePing"
#define MyAppVersion "3.0.0-pre.10"
#define MyAppPublisher "DicodePing"
#define MyAppExeName "DicodePing.exe"

[Setup]
AppId={{4B2D3F4A-2204-4F7C-B2C0-7B6606B587B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DicodePing
DefaultGroupName=DicodePing
OutputDir=..\..\dist
OutputBaseFilename=DicodePing-3.0.0-pre.10-windows-x64-installer
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
SetupIconFile=..\..\apps\desktop\v2rayN.Desktop\Assets\DicodePing.ico

[Files]
Source: "..\..\publish\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\DicodePing"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\DicodePing"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch DicodePing"; Flags: nowait postinstall skipifsilent
