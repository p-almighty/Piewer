"""AI超解像のコア接着剤（Qt非依存）。ai_color.py の双子。

役割:
  ・設定 dict（config.Settings.ai_upscale）の正規化と「有効か」の判定
  ・「このページは拡大すべきか」（原画が表示解像度より小さい時だけ効かせる）の判定
  ・超解像結果のディスクキャッシュ（~/.manga_viewer/ai_upscale/<キー>.webp）
  ・プラグインの upscale を呼んで高解像度化し、キャッシュに保存する純関数

実際の重い処理（モデル/サーバ通信）はプラグイン側にあり、ここは「呼ぶ・しまう・出す」
だけ。非同期実行（UIを止めない）の足回りは reader 側の QRunnable が担う。

設定 dict の形:
  {"on": bool, "plugin": "<provider id>", "opts": {...}, "server": {...}}
"""
import io
import json
import hashlib
from pathlib import Path

from PIL import Image

import config
import plugins

CACHE_DIR = config.APP_DIR / "ai_upscale"

# Piewer が超解像サーバを管理するための設定（着色のSERVER_DEFAULTと別ポート）。
SERVER_DEFAULT = {
    "manage": False,    # Piewer がローカルサーバを起動/停止するか
    "python": "",       # サーバを動かす Python のパス（ai_runtime 流用）
    "repo": "",         # 超解像モデル/コードのフォルダ
    "device": "cpu",    # "cpu" / "cuda"
    "port": 7861,       # 着色(7860)とは別の固定ポート
    "scale": 2,         # 拡大率 2 / 4
    "denoise": 1,       # ノイズ除去の強さ（-1=なし..3、モデル依存）
    "runtime_dir": "",  # 構築一式の保存先（空＝既定 ~/.manga_viewer/ai_runtime）
}

DEFAULT = {"on": False, "plugin": "", "opts": {}, "server": dict(SERVER_DEFAULT)}

# 「拡大すべき」と判断する最小の引き伸ばし率。表示が原画の min_ratio 倍以上に
# 引き伸ばされる（＝原画が表示解像度より小さい）ときだけ超解像を効かせる。
MIN_UPSCALE_RATIO = 1.2


def merge_server(sv) -> dict:
    s = dict(SERVER_DEFAULT)
    if isinstance(sv, dict):
        for k in SERVER_DEFAULT:
            if k in sv:
                s[k] = sv[k]
    # 拡大率・ノイズ除去は妥当な範囲へ丸める
    try:
        s["scale"] = 4 if int(s["scale"]) >= 4 else (2 if int(s["scale"]) >= 2 else 1)
    except Exception:
        s["scale"] = 2
    try:
        s["denoise"] = max(-1, min(3, int(s["denoise"])))
    except Exception:
        s["denoise"] = 1
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
    """ONかつプラグインが指定されているか（実在は signature で確認）。"""
    c = merge(cfg)
    return bool(c["on"] and c["plugin"])


def should_upscale(src_w: int, src_h: int, view_w: int, view_h: int, cfg) -> bool:
    """この原画寸法を、この表示領域で見るとき超解像を効かせるべきか。

    原画→表示の「収める拡大率」(contain) が MIN_UPSCALE_RATIO 以上、すなわち
    原画が表示解像度より十分小さく引き伸ばされる場合だけ True（高解像度な原画には
    無駄な処理をしない）。寸法不明・無効・無効設定では False。
    """
    if not active(cfg):
        return False
    if src_w <= 0 or src_h <= 0 or view_w <= 0 or view_h <= 0:
        return False
    fit = min(view_w / src_w, view_h / src_h)   # >1 で原画が引き伸ばされている
    return fit >= MIN_UPSCALE_RATIO


def _opts_sig(opts: dict) -> str:
    try:
        s = json.dumps(opts, ensure_ascii=False, sort_keys=True)
    except Exception:
        s = repr(opts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


def signature(cfg) -> tuple:
    """キャッシュキー用の軽量シグネチャ。無効/プラグイン不在なら空 ()。

    拡大率・ノイズ除去・プラグインversionを含めるので、設定/更新で自動的に
    キャッシュが分かれる。
    """
    c = merge(cfg)
    if not active(c):
        return ()
    prov = plugins.get_upscaler(c["plugin"])
    if prov is None:
        return ()
    sv = c["server"]
    return (c["plugin"], str(getattr(prov, "version", "")),
            int(sv["scale"]), int(sv["denoise"]), _opts_sig(c["opts"]))


def _effective_opts(c: dict) -> dict:
    """プラグインへ渡す opts に拡大率/ノイズ除去を載せる（opts優先）。"""
    sv = c["server"]
    opts = dict(c["opts"])
    opts.setdefault("scale", int(sv["scale"]))
    opts.setdefault("denoise", int(sv["denoise"]))
    return opts


def cache_path(page_bytes: bytes, cfg) -> Path | None:
    """このページ＋この設定に対する超解像キャッシュの保存先。無効なら None。"""
    sig = signature(cfg)
    if not sig:
        return None
    h = hashlib.sha1(page_bytes).hexdigest()
    key = hashlib.sha1((h + "|" + "|".join(map(str, sig))).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.webp"


def cached_bytes(page_bytes: bytes, cfg) -> bytes | None:
    """高解像度化済みキャッシュがあればそのバイト列（WEBP）を返す。無ければ None。"""
    p = cache_path(page_bytes, cfg)
    if p is not None and p.exists():
        try:
            return p.read_bytes()
        except Exception:
            return None
    return None


def upscale_to_cache(page_bytes: bytes, cfg) -> bytes | None:
    """ページを高解像度化してキャッシュに保存し、結果バイト列を返す（同期・重い）。

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
    prov = plugins.get_upscaler(c["plugin"])
    if prov is None:
        return None
    try:
        src = Image.open(io.BytesIO(page_bytes)).convert("RGB")
        out = prov.upscale(src, _effective_opts(c))
        if out is None:
            return None
        out = out.convert("RGB")
        buf = io.BytesIO()
        out.save(buf, "WEBP", quality=95, method=4)   # 線画を保つため高品質
        data = buf.getvalue()
    except Exception:
        return None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except Exception:
        pass   # 保存に失敗しても結果自体は返す
    return data


def clear_cache() -> int:
    """超解像キャッシュを全削除し、消したファイル数を返す。"""
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
    """超解像キャッシュの合計サイズ（バイト）。"""
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
