; Compile only a fresh, self-tested PyInstaller directory.
#ifndef BundleDir
  #error BundleDir must point to the freshly built LinkForge directory
#endif
#ifndef ReleaseVersion
  #error ReleaseVersion is required
#endif
#ifndef OutputPath
  #error OutputPath is required
#endif

[Setup]
AppId=LinkForge.Desktop
AppName=LinkForge
AppVersion={#ReleaseVersion}
AppPublisher=LinkForge Contributors
AppPublisherURL=https://github.com/ethen887/linkforge
DefaultDirName={localappdata}\Programs\LinkForge
DefaultGroupName=LinkForge
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
LicenseFile={#BundleDir}\LICENSE.txt
OutputDir={#OutputPath}
OutputBaseFilename=LinkForge-v{#ReleaseVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LinkForge.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "\logs\*,\browser-profile\*,\installed.ini,\使用说明.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "安装说明.txt"; DestDir: "{app}"; DestName: "使用说明.txt"; Flags: ignoreversion

[INI]
Filename: "{app}\installed.ini"; Section: "distribution"; Key: "mode"; String: "installed"; Flags: uninsdeleteentry uninsdeletesectionifempty

[UninstallDelete]
Type: files; Name: "{app}\installed.ini"

[Icons]
Name: "{group}\LinkForge"; Filename: "{app}\LinkForge.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 LinkForge"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LinkForge"; Filename: "{app}\LinkForge.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\LinkForge.exe"; Description: "启动 LinkForge"; Flags: nowait postinstall skipifsilent

; Do not delete user data, QSettings or system credentials during uninstall.
