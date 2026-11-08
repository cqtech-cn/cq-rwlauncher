# -*- mode: python ; coding: utf-8 -*-
"""主线单文件构建：旧版程序图标和版本资源，内嵌前端。"""
from pathlib import Path

root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(root / 'backend' / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'frontend' / 'dist'), 'frontend/dist')],
    hiddenimports=['clr', 'webview.platforms.edgechromium', 'webview.platforms.winforms'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'numpy', 'PIL', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='CQRWLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / 'build' / 'icon.ico'),
    version=str(root / 'build' / 'version_info.txt'),
)
