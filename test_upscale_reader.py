"""ReaderView のAI超解像結線テスト（offscreen＋demoサーバ）。

fakeソースを使い _ensure_upscale → worker → キャッシュ までを実際に通す。
should_upscale の正負（小さいページは効く / 大きいページは効かない）も確認。
実データには触れない。直接実行可。
"""
import os
import io
import sys
import time
import importlib.util
import threading
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PIL import Image

app = QApplication(sys.argv)

import config
import ai_upscale
import plugins

TMP = Path(tempfile.mkdtemp(prefix="piewer_upscale_reader_"))
config.SETTINGS_FILE = TMP / "settings.json"
ai_upscale.CACHE_DIR = TMP / "ai_upscale"

_spec = importlib.util.spec_from_file_location(
    "local_upscale_server", Path(__file__).parent / "tools" / "local_upscale_server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

from reader import ReaderView

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def pump(predicate, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeSource:
    def __init__(self, w, h, n=3):
        self.path = "fake"
        self._w, self._h, self._n = w, h, n
    def __len__(self):
        return self._n
    def read(self, i):
        buf = io.BytesIO()
        Image.new("RGB", (self._w, self._h), (30 + i * 10, 80, 120)).save(buf, "PNG")
        return buf.getvalue()
    def ext(self, i):
        return ".png"
    def close(self):
        pass


def main():
    plugins.discover(force=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(srv.DemoBackend(scale=2)))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}/upscale"

    settings = config.Settings()
    settings.ai_upscale = {"on": True, "plugin": "local_upscale",
                           "opts": {"endpoint": endpoint, "mode": "multipart", "max_side": 0},
                           "server": {"scale": 2, "denoise": 1}}

    reader = ReaderView(settings)
    reader.resize(1200, 1000)
    reader.show()
    app.processEvents()
    reader.spread_mode = False
    vw, vh = reader._display.width(), reader._display.height()
    check(vw > 0 and vh > 0, f"表示領域サイズ取得 ({vw}x{vh})")

    try:
        cfg = settings.ai_upscale

        # ① 小さいページ（表示より十分小さい）→ 超解像が走りキャッシュされる
        reader.source = FakeSource(400, 560, n=3)
        raw0 = reader.source.read(0)
        check(ai_upscale.should_upscale(400, 560, vw, vh, cfg) is True,
              "should_upscale: 400x560 は True（小さい）")
        reader._ensure_upscale(0)
        got = pump(lambda: ai_upscale.cached_bytes(raw0, cfg) is not None)
        check(got, "小さいページ: 超解像キャッシュが生成された")
        if got:
            im = Image.open(io.BytesIO(ai_upscale.cached_bytes(raw0, cfg)))
            check(im.size == (800, 1120), f"出力が2倍(800x1120) 実={im.size}")
        # _page_bytes が超解像後バイトを返す
        check(reader._page_bytes(0) == ai_upscale.cached_bytes(raw0, cfg),
              "_page_bytes: 超解像済みバイトを返す")

        # ② 大きいページ（表示より大きい）→ 走らない
        reader.source = FakeSource(2400, 3360, n=3)
        check(ai_upscale.should_upscale(2400, 3360, vw, vh, cfg) is False,
              "should_upscale: 2400x3360 は False（大きい）")
        reader._up_inflight.clear()
        reader._ensure_upscale(0)
        # 何も予約されない（inflightが空のまま・少し待っても変化なし）
        idle = not pump(lambda: len(reader._up_inflight) > 0, timeout=1.0)
        check(idle, "大きいページ: 超解像を予約しない")

        # ③ 無効化すると _page_bytes は原画
        reader.source = FakeSource(400, 560, n=3)
        settings.ai_upscale = {"on": False}
        raw = reader.source.read(0)
        check(reader._page_bytes(0) == raw, "無効化: _page_bytes は原画を返す")
    finally:
        httpd.shutdown()
        reader.close()

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
