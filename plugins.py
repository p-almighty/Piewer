"""Piewer プラグイン基盤（スリム・重い依存なし）。

本体は「画像を渡す→着色画像が返る」という細い契約だけを知る。実際の着色処理
（クラウドAPI / ローカルサーバ / ローカルモデル等）はプラグイン側に隔離するため、
本体サイズも依存も増えない。サードパーティ製プラグインも、規約に沿って所定の
フォルダに置けばそのまま読み込まれて動く。

探索場所:
  ① ~/.manga_viewer/plugins/         （ユーザーが後から入れる場所）
  ② <exe または本体スクリプト>/plugins/  （同梱・配布プラグイン）

プラグインの形:
  ・単一ファイル          plugins/foo.py
  ・フォルダ（推奨）       plugins/foo/plugin.py  （helper等を同梱できる）
  いずれも `register()` を公開し、着色プロバイダ（下記の契約）を返す。

着色プロバイダの契約（ダックタイピング。必須属性が揃っていれば良い）:
  id: str                      一意なID（英数）
  name: str                    表示名
  version: str                 版（キャッシュ無効化に使う）
  colorize(img, opts) -> img   PIL.Image(RGB) を受け取り着色した PIL.Image を返す
  ── 任意 ──
  available() -> (bool, str)   使える状態か（依存/接続チェック）と理由
  description: str             説明文
  config_fields() -> list      設定項目の宣言（UIが動的に描画）。各項目:
       {"key","label","type":"text|password|int|choice|bool",
        "default", "choices":[...], "help"}
"""
import sys
import importlib.util
import traceback
from pathlib import Path

import config

# 着色プロバイダに最低限必要な属性
_REQUIRED = ("id", "name", "version", "colorize")

# 探索結果のキャッシュ
_colorizers: dict[str, object] = {}
_errors: list[tuple[str, str]] = []
_loaded = False


def _builtin_dirs() -> list[Path]:
    """配布物に同梱したプラグイン置き場。

    onefile EXE では実行時展開先(_MEIPASS)に同梱物が入るのでそこを見る。
    さらに exe / 本体スクリプトの隣も見て、ユーザーが手で置いた物も拾う。
    """
    out: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            out.append(Path(meipass) / "plugins")
        out.append(Path(sys.executable).resolve().parent / "plugins")
    else:
        out.append(Path(__file__).resolve().parent / "plugins")
    return out


def plugin_dirs() -> list[Path]:
    """プラグインを探すディレクトリ（重複除去・順序維持）。存在チェックはしない。

    ユーザー追加分(~/.manga_viewer/plugins)を先に見るので、同IDなら同梱より優先される。
    """
    dirs: list[Path] = []
    for d in [config.APP_DIR / "plugins", *_builtin_dirs()]:
        rd = d.resolve()
        if rd not in dirs:
            dirs.append(rd)
    return dirs


def ensure_user_plugin_dir() -> Path:
    """ユーザー用プラグインフォルダを作成して返す（無ければ作る）。"""
    d = config.APP_DIR / "plugins"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _entry_files() -> list[tuple[str, Path]]:
    """読み込むべき (モジュール名, ファイルパス) を集める。"""
    found: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    for d in plugin_dirs():
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir(), key=lambda p: p.name.lower()):
            name = entry.name
            if name.startswith((".", "_")):
                continue
            if entry.is_dir():
                pf = entry / "plugin.py"
                if pf.is_file():
                    mod = entry.name
                    if mod not in seen_names:
                        seen_names.add(mod); found.append((mod, pf))
            elif entry.is_file() and entry.suffix.lower() == ".py":
                mod = entry.stem
                if mod not in seen_names:
                    seen_names.add(mod); found.append((mod, entry))
    return found


def _load_one(mod_name: str, path: Path):
    """1ファイルを読み込み register() の返すプロバイダを取り込む（失敗は記録のみ）。"""
    try:
        spec = importlib.util.spec_from_file_location(f"piewer_plugin_{mod_name}", path)
        if spec is None or spec.loader is None:
            raise ImportError("spec を作成できません")
        module = importlib.util.module_from_spec(spec)
        # フォルダ型プラグインが同梱helperを import できるよう、親ディレクトリを通す
        parent = str(path.parent)
        added = parent not in sys.path
        if added:
            sys.path.insert(0, parent)
        try:
            spec.loader.exec_module(module)
        finally:
            if added:
                try: sys.path.remove(parent)
                except ValueError: pass
        register = getattr(module, "register", None)
        if not callable(register):
            raise AttributeError("register() がありません")
        provider = register()
        if provider is None:
            raise ValueError("register() が None を返しました")
        missing = [a for a in _REQUIRED if not hasattr(provider, a)]
        if missing:
            raise TypeError("プロバイダに属性が不足: " + ", ".join(missing))
        if not callable(getattr(provider, "colorize")):
            raise TypeError("colorize が呼び出し可能ではありません")
        pid = str(provider.id)
        # 同IDが既にあれば先勝ち（ユーザーフォルダが配布同梱より優先される順序）
        if pid not in _colorizers:
            setattr(provider, "_dir", str(path.parent))
            _colorizers[pid] = provider
    except Exception:
        _errors.append((str(path), traceback.format_exc(limit=4)))


def discover(force: bool = False) -> list[object]:
    """全プラグインを探索して着色プロバイダ一覧を返す（結果はキャッシュ）。"""
    global _loaded
    if _loaded and not force:
        return list(_colorizers.values())
    _colorizers.clear(); _errors.clear()
    for mod_name, path in _entry_files():
        _load_one(mod_name, path)
    _loaded = True
    return list(_colorizers.values())


def colorizers() -> list[object]:
    """着色プロバイダ一覧（未探索なら探索する）。"""
    return discover()


def get_colorizer(pid: str | None):
    """ID指定で着色プロバイダを返す。無ければ None。"""
    if not pid:
        return None
    discover()
    return _colorizers.get(str(pid))


def load_errors() -> list[tuple[str, str]]:
    """読み込みに失敗したプラグインの (パス, トレース) 一覧。"""
    discover()
    return list(_errors)


def provider_available(provider) -> tuple[bool, str]:
    """プロバイダが使える状態かを安全に問い合わせる（available 未実装なら True 扱い）。"""
    fn = getattr(provider, "available", None)
    if not callable(fn):
        return (True, "")
    try:
        ok, reason = fn()
        return (bool(ok), str(reason or ""))
    except Exception as e:
        return (False, str(e))


def provider_config_fields(provider) -> list[dict]:
    """プロバイダが宣言する設定項目（未実装なら空）。"""
    fn = getattr(provider, "config_fields", None)
    if not callable(fn):
        return []
    try:
        fields = fn()
        return list(fields) if fields else []
    except Exception:
        return []
