#ifndef MyAppVersion
  #error MyAppVersion must be passed to ISCC
#endif

#define MyAppName "档口开单系统"
#define MyAppExeName "档口开单系统.exe"

[Setup]
AppId={{4E56B00C-BC27-4B31-8BB6-D955234DD1A8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=货有数
DefaultDirName={localappdata}\Programs\HuoYouShu
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\outputs
OutputBaseFilename=HuoYouShu-Setup-{#MyAppVersion}-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=Local\HuoYouShu-Counter
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "dist\档口开单系统\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\档口开单系统"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autoprograms}\档口开单系统"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动档口开单系统"; Flags: nowait postinstall skipifsilent
