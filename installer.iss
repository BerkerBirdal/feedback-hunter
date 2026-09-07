; Feedback Hunter — Inno Setup kurulum betiği
; Derleme: ISCC /DMyAppVersion=0.9 installer.iss  (sürüm CI'da tag'den geçilir)

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Feedback Hunter"
#define MyAppPublisher "Berker Birdal"
#define MyAppURL "https://fbhunter.berkerbirdal.com"
#define MyAppExeName "FeedbackHunter.exe"

[Setup]
AppId={{9C4B7F2E-3A61-4D58-9E2C-FB0A5D7E1C34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\Feedback Hunter
DefaultGroupName=Feedback Hunter
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=feedback_hunter_windows_setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; GroupDescription: "Ek kısayollar:"; Flags: checkedonce

[Files]
Source: "dist\FeedbackHunter.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Feedback Hunter"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Feedback Hunter Kaldır"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Feedback Hunter"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Feedback Hunter'ı başlat"; Flags: nowait postinstall skipifsilent
