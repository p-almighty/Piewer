"""local_upscale プラグインの統合テスト（demoサーバ＋実プラグイン＋ai_upscale）。

demo超解像サーバをスレッド起動し、実際に同梱プラグイン local_upscale を discover→
ai_upscale.upscale_to_cache まで通して 2倍画像がキャッシュされることを確認する。
実データには触れない（キャッシュ先を一時dirへ差し替え）。直接実行可。
"""
import io
import sys
import importlib.util
import threading
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer

from PIL import Image

import config
import plugins
import ai_upscale

# キャッシュ先を一時dirへ（実データ保護）
TMP = Path(tempfile.mkdtemp(prefix="piewer_upscale_plug_"))
ai_upscale.CACHE_DIR = TMP / "ai_upscale"

# demoサーバをモジュールとして読み込む
_spec = importlib.util.spec_from_file_location(
    "local_upscale_server", Path(__file__).parent / "tools" / "local_upscale_server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def png_bytes(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (60, 120, 80)).save(buf, "PNG")
    return buf.getvalue()


def main():
    # ① 同梱プラグインの探索（強制再探索）
    plugins.discover(force=True)
    up = plugins.get_upscaler("local_upscale")
    check(up is not None, "discover: local_upscale を upscaler として検出")
    check(plugins.get_colorizer("local_upscale") is None,
          "分離: local_upscale は colorizer 側に出ない")
    check(plugins.get_colorizer("connector") is not None,
          "既存: connector は従来どおり colorizer として検出")
    check(plugins.get_upscaler("connector") is None,
          "分離: connector は upscaler 側に出ない")
    if not plugins.load_errors():
        check(True, "プラグイン読み込みエラーなし")
    else:
        check(False, f"プラグイン読み込みエラー: {plugins.load_errors()}")

    # ② demoサーバ起動（2倍）
    backend = srv.DemoBackend(scale=2)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(backend))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}/upscale"
    try:
        # ③ プラグイン単体（multipart）
        img = Image.new("RGB", (100, 140), (200, 30, 30))
        out = up.upscale(img, {"endpoint": endpoint, "mode": "multipart"})
        check(out.size == (200, 280), f"plugin multipart: 2倍(200x280) 実={out.size}")
        # base64-json経路
        out2 = up.upscale(img, {"endpoint": endpoint, "mode": "base64-json"})
        check(out2.size == (200, 280), f"plugin base64-json: 2倍 実={out2.size}")

        # ④ ai_upscale 全パイプライン（signature→upscale_to_cache→cache hit）
        cfg = {"on": True, "plugin": "local_upscale",
               "opts": {"endpoint": endpoint, "mode": "multipart"},
               "server": {"scale": 2, "denoise": 1}}
        check(ai_upscale.signature(cfg) != (), "ai_upscale.signature: 有効")
        raw = png_bytes(120, 160)
        data = ai_upscale.upscale_to_cache(raw, cfg)
        check(data is not None, "upscale_to_cache: 結果が返る")
        im = Image.open(io.BytesIO(data))
        check(im.size == (240, 320), f"pipeline: 2倍(240x320) 実={im.size}")
        # 2回目はキャッシュヒット（サーバを止めても返る）
        httpd.shutdown()
        cached = ai_upscale.cached_bytes(raw, cfg)
        check(cached == data, "cache: サーバ停止後もキャッシュから取得")
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
