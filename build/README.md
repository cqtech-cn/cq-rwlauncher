# Windows 安装包构建指引

本目录沿用旧版主线安装向导的 AppId、简体中文语言文件、程序与安装图标、向导图片及用户协议。版本号在 `installer.iss` 与 `version_info.txt` 中同步维护（当前 3.10）。

## 准备

- Windows、Python 3.10+、Node.js、Inno Setup 6。
- 安装后端依赖：`python -m pip install -r requirements.txt`
- 前端依赖：在 `frontend` 目录执行 `npm ci`。

## 构建

从 `启动器本体` 目录执行以下命令：

```powershell
npm run build --prefix frontend
python -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller build/rwlauncher.spec
python -c "import datetime,json,pathlib; now=datetime.datetime.now(); pathlib.Path('dist/build_meta.json').write_text(json.dumps({'build_date':now.strftime('%Y-%m-%d'),'build_time':now.strftime('%Y-%m-%d %H:%M:%S')},ensure_ascii=False,indent=2),encoding='utf-8')"
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "build\installer.iss"
```

如果 Inno Setup 安装在其他位置，请将最后一条命令中的 `ISCC.exe` 路径改为实际安装路径。

主程序输出为 `dist/CQRWLauncher.exe`；安装程序输出为 `build/installer_output/CQRWLauncher-Setup-3.10.exe`。安装向导包含许可协议、安装位置选择、可选桌面快捷方式及安装完成后运行程序。安装时不覆盖已有的 `config.json`，也不捆绑游戏本体。`frpc.exe` 当前未提供，需使用内网穿透功能时自行放在安装目录的 `binaries/frpc/` 下。
