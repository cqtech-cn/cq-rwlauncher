; CQ RWLauncher 主线安装向导（沿用旧版 AppId、图标、协议和中文向导）
#define MyAppName "CQ RWLauncher"
#define MyAppVersion "3.10"
#define MyAppPublisher "CQFISH & 喵酱"
#define MyAppURL "http://cqrwldocs.cqfishnet.cn/"
#define MyAppExeName "CQRWLauncher.exe"

[Setup]
AppId={{B8E3F5C1-3D7A-4F1E-9C2B-5A8E7D6F1A2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
LicenseFile=..\..\非本体文件\文档资料\用户协议.txt
OutputDir=installer_output
OutputBaseFilename=CQRWLauncher-Setup-{#MyAppVersion}
SetupIconFile=setup_icon.ico
WizardImageFile=wizard_side.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"

[Messages]
WelcomeLabel2=本向导将引导你完成 [name/ver] 的安装。%n%n安装后可在开始菜单中启动，也可选择创建桌面快捷方式。游戏文件默认安装到 D:\RustedWarfare\，可在启动器设置中修改。%n%n安装本应用即代表你已阅读并同意本软件的全部协议与文档，详细内容请访问 http://cqrwldocs.cqfishnet.cn/ 查看。

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\CQRWLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\build_meta.json"; DestDir: "{app}"; Flags: ignoreversion
; 不打包 config.json 或缺失的 frpc.exe，保留用户原有配置和数据

[Dirs]
Name: "{app}\logs"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup: Boolean;
begin
  Result := True;
  if RegKeyExists(HKEY_CURRENT_USER,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1') then
  begin
    if MsgBox('检测到已安装的 {#MyAppName}，是否继续？' + #13#10 +
              '选择"是"将覆盖安装，"否"退出。',
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
