# -*- mode: python ; coding: utf-8 -*-
# Piewer ビルド設定（PyInstaller）
# ビルド: pyinstaller Piewer.spec

block_cipher = None

a = Analysis(
    ['manga_viewer.py'],
    pathex=[],
    binaries=[],
    datas=[('piewer.ico', '.'),
           ('plugins', 'plugins'),    # 同梱プラグイン（AI着色/超解像のリファレンス等）
           ('tools', 'tools')],       # Piewerが起動するローカル着色/超解像サーバ
    hiddenimports=['fitz', 'auto_tag', 'folder_view',
                   'plugins', 'ai_color', 'ai_server', 'ai_runtime', 'ai_upscale',   # PyMuPDF / 関数内importの自作モジュール
                   # 同梱プラグイン(plugins/connector)が動的ロード時にimportする標準ライブラリ。
                   # PyInstallerの静的解析はプラグインを辿らないため明示しないと同梱されず、
                   # frozen exeでプラグインが読み込めず「着色プラグインが見つかりません」になる。
                   'uuid', 'urllib.request', 'urllib.error'],
    hookspath=[],
    runtime_hooks=[],
    # 本体が使わない重量級パッケージを除外する。
    # 開発環境に torch/pandas/scipy 等が入っていると、pymupdf.table の
    # 遅延 import(pandas) を静的解析が拾い pandas→scipy→torch と芋づるで
    # 取り込まれ、exe が 82MB → 2.4GB に膨張する。
    # AI着色/超解像の重い依存は別の standalone ランタイム
    # (~/.manga_viewer/ai_runtime) 側にあり、本体には不要。
    excludes=['torch', 'torchvision', 'torchaudio', 'torchgen', 'functorch',
              'pandas', 'pyarrow', 'fastparquet', 'scipy', 'sympy', 'mpmath',
              'networkx', 'numpy', 'cv2', 'sklearn', 'skimage', 'matplotlib',
              'IPython', 'tzdata', 'fsspec'],
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
    upx=False,                # UPX圧縮はアンチウイルス誤検知の主因のため無効化
    runtime_tmpdir=None,
    console=False,            # GUIアプリなのでコンソール非表示
    icon='piewer.ico',        # exeのアイコン
    version='version_info.txt',  # exeにメタデータを埋め込み誤検知を低減
)
