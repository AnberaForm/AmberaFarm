; Player installer: a single Setup EXE, no source tree or editor to distribute.
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#ifndef OutputFolder
  #error OutputFolder is required
#endif

[Setup]
AppId={{D516921B-5AFB-468A-9027-0C832411A960}
AppName=アンベラ牧場
AppVersion={#AppVersion}
AppPublisher=AnberaForm
AppPublisherURL=https://github.com/AnberaForm/AmberaFarm
DefaultDirName={localappdata}\Programs\AmberaFarm
DefaultGroupName=アンベラ牧場
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=yes
DisableProgramGroupPage=yes
WizardStyle=modern
OutputDir={#OutputFolder}
OutputBaseFilename=AmberaFarm_Setup_v{#AppVersion}
Compression=lzma2/fast
SolidCompression=yes
UninstallDisplayIcon={app}\AmberaFarm.exe
AppMutex=Local\AmberaFarm_OneLauncher_v1
SetupMutex=AmberaFarm_Setup
CloseApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成する"; GroupDescription: "ショートカット"

[Files]
Source: "{#ReleaseDir}\AmberaFarm.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\app\AmberaGame.exe"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "{#ReleaseDir}\version.json"; DestDir: "{app}"; Attribs: hidden; Flags: ignoreversion

[Icons]
Name: "{group}\アンベラ牧場"; Filename: "{app}\AmberaFarm.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\アンベラ牧場"; Filename: "{app}\AmberaFarm.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AmberaFarm.exe"; Description: "アンベラ牧場を起動する"; Flags: nowait postinstall skipifsilent

; No profile/save directory is listed in UninstallDelete. Uninstall preserves saves.
