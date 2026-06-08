# -*- mode: python ; coding: utf-8 -*-
# Piewer ビルド設定（PyInstaller）
# ビルド: pyinstaller Piewer.spec

block_cipher = None

a = Analysis(
    ['manga_viewer.py'],
    pathex=[],
    binaries=[],
    datas=[('piewer.ico', '.')],   # アイコンを実行ファイルに同梱
    hiddenimports=['fitz', 'auto_tag', 'folder_view'],   # PyMuPDF / 関数内importの自作モジュール
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Piewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,            # GUIアプリなのでコンソール非表示
    icon='piewer.ico',        # exeのアイコン
)
