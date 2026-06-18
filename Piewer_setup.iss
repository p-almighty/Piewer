; Piewer インストーラ定義（Inno Setup 6）
; コンパイル: "ISCC.exe" Piewer_setup.iss
; 出力: Output\Piewer_Setup.exe

#define MyAppName "Piewer"
#define MyAppVersion "1.90"
#define MyAppPublisher "Piewer"
#define MyAppExeName "Piewer.exe"

[Setup]
AppId={{B3A7E9C2-8F4D-4E1A-9C5B-PIEWER000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=Piewer_Setup
SetupIconFile=piewer.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 64bitアプリとしてインストール
ArchitecturesInstallIn64BitMode=x64compatible
; Program Filesへ書き込むため管理者権限を要求
PrivilegesRequired=admin

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成する"; GroupDescription: "追加アイコン:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "readme.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
; スタートメニュー（プログラム一覧に表示）
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
; デスクトップ（タスク選択時のみ）
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; インストール完了後にすぐ起動するオプション
Filename: "{app}\{#MyAppExeName}"; Description: "{#MyAppName} を起動する"; Flags: nowait postinstall skipifsilent
