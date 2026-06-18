"""local_upscale_server の配線テスト（demo backend・依存なし）。

ThreadingHTTPServer をスレッドで起動し、multipart と JSON(base64) の両経路で
画像をPOST → 2倍に拡大されたPNGが返ることを確認する。実データには触れない。
直接 `python test_upscale_server.py` で実行。
"""
import io
import sys
import json
import base64
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image

import importlib.util
from pathlib import Path

# tools/local_upscale_server.py をモジュールとして読み込む
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
    Image.new("RGB", (w, h), (50, 90, 140)).save(buf, "PNG")
    return buf.getvalue()


def post(url, data, ctype):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def main():
    # weight名ヘルパの単体確認
    check(srv.cugan_weight_name(2, 1) == "up2x-latest-denoise1x.pth",
          "cugan_weight_name: 2x/denoise1")
    check(srv.cugan_weight_name(2, -1) == "up2x-latest-conservative.pth",
          "cugan_weight_name: conservative")
    check(srv.cugan_weight_name(4, 3) == "up4x-latest-denoise3x.pth",
          "cugan_weight_name: 4x/denoise3")
    check(srv.cugan_weight_name(4, 1) == "up4x-latest-denoise3x.pth",
          "cugan_weight_name: 4xのdenoise1→denoise3x（存在する方）")

    backend = srv.DemoBackend(scale=2)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(backend))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}/upscale"
    try:
        raw = png_bytes(120, 160)

        # ① multipart/form-data
        boundary = "----piewertest"
        body = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="image"; filename="p.png"\r\n'
                "Content-Type: image/png\r\n\r\n").encode() + raw + \
               f"\r\n--{boundary}--\r\n".encode()
        st, out = post(base, body, f"multipart/form-data; boundary={boundary}")
        im = Image.open(io.BytesIO(out))
        check(st == 200 and im.size == (240, 320), f"multipart: 200で2倍(240x320) 実={im.size}")

        # ② application/json (base64 dataURL)
        payload = json.dumps(
            {"image": "data:image/png;base64," + base64.b64encode(raw).decode()}).encode()
        st2, out2 = post(base, payload, "application/json")
        im2 = Image.open(io.BytesIO(out2))
        check(st2 == 200 and im2.size == (240, 320), f"json: 200で2倍(240x320) 実={im2.size}")

        # ③ GET でサーバ情報
        with urllib.request.urlopen(base, timeout=10) as r:
            txt = r.read().decode("utf-8", "ignore")
        check("demo" in txt, "GET: backend名(demo)を返す")
    finally:
        httpd.shutdown()

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
