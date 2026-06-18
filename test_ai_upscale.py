"""ai_upscale / plugins(upscaler) / Settings.ai_upscale の単体テスト。

実データ（~/.manga_viewer）には一切触れない。キャッシュ先と設定ファイルを
一時ディレクトリへ差し替えてから対象を叩く。直接 `python test_ai_upscale.py` で実行。
"""
import io
import sys
import json
import tempfile
from pathlib import Path

from PIL import Image

import config
import plugins
import ai_upscale

TMP = Path(tempfile.mkdtemp(prefix="piewer_upscale_test_"))
# 実データ保護: キャッシュ先と設定ファイルを一時パスへ
ai_upscale.CACHE_DIR = TMP / "ai_upscale"
config.SETTINGS_FILE = TMP / "settings.json"

_fails = []


def check(cond, msg):
    if cond:
        print(f"[OK] {msg}")
    else:
        print(f"[NG] {msg}")
        _fails.append(msg)


def png_bytes(w, h, color=(40, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# ── ダミー超解像プラグインを登録（実モデル不要）──────────────
class FakeUpscaler:
    id = "fake_up"
    name = "Fake Upscaler"
    version = "1.0"
    last_opts = None

    def upscale(self, img, opts):
        FakeUpscaler.last_opts = dict(opts)
        scale = int(opts.get("scale", 2))
        return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def install_fake_plugin():
    plugins._colorizers.clear(); plugins._upscalers.clear(); plugins._errors.clear()
    prov = FakeUpscaler()
    plugins._upscalers[prov.id] = prov
    plugins._loaded = True   # discover() を再実行させない


# ── 1. merge / clamp ────────────────────────────────────────
def test_merge():
    c = ai_upscale.merge({"on": True, "plugin": "fake_up",
                          "server": {"scale": 9, "denoise": 99}})
    check(c["on"] is True and c["plugin"] == "fake_up", "merge: on/plugin 反映")
    check(c["server"]["scale"] == 4, "merge_server: scale 上限4へ丸め")
    check(c["server"]["denoise"] == 3, "merge_server: denoise 上限3へ丸め")
    c2 = ai_upscale.merge({"server": {"scale": 1, "denoise": -5}})
    check(c2["server"]["scale"] == 1 and c2["server"]["denoise"] == -1,
          "merge_server: 下限へ丸め")
    check(ai_upscale.active({"on": True, "plugin": "x"}) is True
          and ai_upscale.active({"on": True, "plugin": ""}) is False,
          "active: on かつ plugin 指定で True")


# ── 2. should_upscale 判定 ──────────────────────────────────
def test_should_upscale():
    cfg = {"on": True, "plugin": "fake_up"}
    # 原画 600x850 を 1200x1080 で見る → 約1.27倍に引き伸ばし → 効かせる
    check(ai_upscale.should_upscale(600, 850, 1200, 1080, cfg) is True,
          "should_upscale: 小さい原画は True")
    # 原画 2000x2800 を 1080 高さ → 縮小表示 → 効かせない
    check(ai_upscale.should_upscale(2000, 2800, 1500, 1080, cfg) is False,
          "should_upscale: 大きい原画は False")
    # ちょうど等倍付近（1.1倍）は閾値1.2未満 → False
    check(ai_upscale.should_upscale(1000, 1000, 1100, 1100, cfg) is False,
          "should_upscale: わずかな拡大(1.1x)は False")
    # 無効設定なら常に False
    check(ai_upscale.should_upscale(100, 100, 1000, 1000, {"on": False}) is False,
          "should_upscale: 無効設定は False")
    # 不正寸法は False
    check(ai_upscale.should_upscale(0, 100, 1000, 1000, cfg) is False,
          "should_upscale: 寸法0は False")


# ── 3. signature が設定で変わる ─────────────────────────────
def test_signature():
    base = {"on": True, "plugin": "fake_up", "server": {"scale": 2, "denoise": 1}}
    s2 = ai_upscale.signature(base)
    s4 = ai_upscale.signature({**base, "server": {"scale": 4, "denoise": 1}})
    sd = ai_upscale.signature({**base, "server": {"scale": 2, "denoise": 2}})
    so = ai_upscale.signature({**base, "opts": {"extra": 1}})
    check(s2 and s4 and s2 != s4, "signature: scale で変わる")
    check(s2 != sd, "signature: denoise で変わる")
    check(s2 != so, "signature: opts で変わる")
    check(ai_upscale.signature({"on": False}) == (), "signature: 無効は空タプル")
    # プラグイン不在なら空
    check(ai_upscale.signature({"on": True, "plugin": "missing"}) == (),
          "signature: プラグイン不在は空タプル")


# ── 4. キャッシュ往復 + プラグイン呼び出し ──────────────────
def test_cache_roundtrip():
    cfg = {"on": True, "plugin": "fake_up", "server": {"scale": 2, "denoise": 1}}
    raw = png_bytes(200, 280)
    check(ai_upscale.cached_bytes(raw, cfg) is None, "cache: 初回はミス")
    out = ai_upscale.upscale_to_cache(raw, cfg)
    check(out is not None, "upscale_to_cache: 結果が返る")
    # 拡大率がプラグインへ渡っている
    check(FakeUpscaler.last_opts.get("scale") == 2, "opts: scale がプラグインへ渡る")
    # 出力サイズが2倍
    im = Image.open(io.BytesIO(out))
    check(im.size == (400, 560), "出力が2倍解像度(400x560)")
    # 2回目はキャッシュヒット（プラグインを呼ばない＝last_opts変化なし）
    FakeUpscaler.last_opts = None
    out2 = ai_upscale.cached_bytes(raw, cfg)
    check(out2 == out, "cache: 2回目はヒットで同一")
    check(FakeUpscaler.last_opts is None, "cache: ヒット時プラグイン未呼び出し")
    # キャッシュ集計/削除
    check(ai_upscale.cache_size_bytes() > 0, "cache_size_bytes > 0")
    n = ai_upscale.clear_cache()
    check(n >= 1 and ai_upscale.cache_size_bytes() == 0, "clear_cache: 全消去")


# ── 5. plugins の upscaler 探索 ─────────────────────────────
def test_plugins_registry():
    check(plugins.get_upscaler("fake_up") is not None, "get_upscaler: ID取得")
    check(plugins.get_upscaler("nope") is None, "get_upscaler: 不在は None")
    check(any(p.id == "fake_up" for p in plugins.upscalers()), "upscalers(): 一覧に含む")
    # colorize を持たないので colorizer 側には出ない
    check(plugins.get_colorizer("fake_up") is None,
          "分離: upscaler は colorizer 側に出ない")


# ── 6. Settings.ai_upscale の保存/復元 ──────────────────────
def test_settings_roundtrip():
    st = config.Settings()
    st.ai_upscale = {"on": True, "plugin": "fake_up", "server": {"scale": 4}}
    st.save()
    raw = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    check(raw.get("ai_upscale", {}).get("plugin") == "fake_up",
          "Settings: ai_upscale が保存される")
    st2 = config.Settings()
    check(st2.ai_upscale.get("server", {}).get("scale") == 4,
          "Settings: ai_upscale が復元される")


def main():
    install_fake_plugin()
    test_merge()
    test_should_upscale()
    test_signature()
    test_cache_roundtrip()
    test_plugins_registry()
    test_settings_roundtrip()
    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} 件 -> {_fails}")
        sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
