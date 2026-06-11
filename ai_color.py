"""AI着色のコア接着剤（Qt非依存）。

役割:
  ・設定 dict（config.Settings.ai_color）の正規化と「有効か」の判定
  ・着色結果のディスクキャッシュ（~/.manga_viewer/ai_color/<キー>.webp）
  ・プラグインの colorize を呼んで着色し、キャッシュに保存する純関数

実際の重い処理（モデル/API通信）はプラグイン側にあり、ここは「呼ぶ・しまう・出す」
だけ。非同期実行（UIを止めない）の足回りは reader 側の QRunnable が担う。

設定 dict の形:
  {"on": bool, "plugin": "<provider id>", "opts": {<プラグイン固有の設定>}}
"""
import io
import json
import hashlib
from pathlib import Path

from PIL import Image

import config
import plugins

CACHE_DIR = config.APP_DIR / "ai_color"

# Piewer が着色サーバを管理するための設定（フェーズA）。manage=True で自動起動。
SERVER_DEFAULT = {
    "manage": False,   # Piewer がローカルサーバを起動/停止するか
    "python": "",      # 着色サーバを動かす Python のパス（フェーズBで自動構築）
    "repo": "",        # 着色モデルのフォルダ（manga-colorization-v2 を clone した場所）
    "device": "cpu",   # "cpu" / "cuda"
    "port": 7860,      # 固定ポート（キャッシュ安定のため既定固定）
    "saturation": 1.0,  # 色の濃さ
    "runtime_dir": "",  # 自動構築一式の保存先（空＝既定 ~/.manga_viewer/ai_runtime）
}

DEFAULT = {"on": False, "plugin": "", "opts": {}, "server": dict(SERVER_DEFAULT)}


def merge_server(sv) -> dict:
    s = dict(SERVER_DEFAULT)
    if isinstance(sv, dict):
        for k in SERVER_DEFAULT:
            if k in sv:
                s[k] = sv[k]
    return s


def merge(cfg) -> dict:
    c = dict(DEFAULT)
    c["server"] = dict(SERVER_DEFAULT)
    if isinstance(cfg, dict):
        if "on" in cfg:
            c["on"] = bool(cfg["on"])
        if cfg.get("plugin"):
            c["plugin"] = str(cfg["plugin"])
        if isinstance(cfg.get("opts"), dict):
            c["opts"] = dict(cfg["opts"])
        c["server"] = merge_server(cfg.get("server"))
    return c


def active(cfg) -> bool:
    """ONかつプラグインが指定されているか（プラグインの実在は signature で確認）。"""
    c = merge(cfg)
    return bool(c["on"] and c["plugin"])


def _opts_sig(opts: dict) -> str:
    try:
        s = json.dumps(opts, ensure_ascii=False, sort_keys=True)
    except Exception:
        s = repr(opts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


def signature(cfg) -> tuple:
    """キャッシュキー用の軽量シグネチャ。無効/プラグイン不在なら空 ()。

    プラグインの version も含めるので、プラグイン更新で自動的にキャッシュが分かれる。
    """
    c = merge(cfg)
    if not active(c):
        return ()
    prov = plugins.get_colorizer(c["plugin"])
    if prov is None:
        return ()
    return (c["plugin"], str(getattr(prov, "version", "")), _opts_sig(c["opts"]))


def cache_path(page_bytes: bytes, cfg) -> Path | None:
    """このページ＋この設定に対する着色キャッシュの保存先。無効なら None。"""
    sig = signature(cfg)
    if not sig:
        return None
    h = hashlib.sha1(page_bytes).hexdigest()
    key = hashlib.sha1((h + "|" + "|".join(map(str, sig))).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.webp"


def cached_bytes(page_bytes: bytes, cfg) -> bytes | None:
    """着色済みキャッシュがあればそのバイト列（WEBP）を返す。無ければ None。"""
    p = cache_path(page_bytes, cfg)
    if p is not None and p.exists():
        try:
            return p.read_bytes()
        except Exception:
            return None
    return None


def colorize_to_cache(page_bytes: bytes, cfg) -> bytes | None:
    """ページを着色してキャッシュに保存し、着色済みバイト列を返す（同期・重い）。

    ワーカースレッドから呼ぶこと。失敗時は None（呼び出し側は原画を表示する）。
    既にキャッシュ済みならプラグインを呼ばずにそれを返す。
    """
    p = cache_path(page_bytes, cfg)
    if p is None:
        return None
    if p.exists():
        try:
            return p.read_bytes()
        except Exception:
            pass
    c = merge(cfg)
    prov = plugins.get_colorizer(c["plugin"])
    if prov is None:
        return None
    try:
        src = Image.open(io.BytesIO(page_bytes)).convert("RGB")
        out = prov.colorize(src, dict(c["opts"]))
        if out is None:
            return None
        out = out.convert("RGB")
        buf = io.BytesIO()
        out.save(buf, "WEBP", quality=90, method=4)
        data = buf.getvalue()
    except Exception:
        return None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except Exception:
        pass   # 保存に失敗しても着色結果自体は返す
    return data


def clear_cache() -> int:
    """着色キャッシュを全削除し、消したファイル数を返す。"""
    n = 0
    try:
        for f in CACHE_DIR.glob("*.webp"):
            try:
                f.unlink(); n += 1
            except Exception:
                pass
    except Exception:
        pass
    return n


def cache_size_bytes() -> int:
    """着色キャッシュの合計サイズ（バイト）。"""
    total = 0
    try:
        for f in CACHE_DIR.glob("*.webp"):
            try:
                total += f.stat().st_size
            except Exception:
                pass
    except Exception:
        pass
    return total
