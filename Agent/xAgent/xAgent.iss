; xAgent Windows 安装包脚本 (Inno Setup 6)
; 用法: ISCC.exe xAgent.iss

#define MyAppName      "xAgent"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "xAgent Team"
#define MyAppExeName   "xAgent.exe"

[Setup]
AppId={{8E1F2A3B-4C5D-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=dist
OutputBaseFilename=xAgent_Setup-{#MyAppVersion}
SetupIconFile=
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "startmenuicon"; Description: "创建开始菜单项"; GroupDescription: "附加图标:"

[Files]
Source: "dist\xAgent.exe";            DestDir: "{app}"; Flags: ignoreversion
Source: "config.ini";                  DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";                   DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
