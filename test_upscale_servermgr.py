"""UpscaleServerManager の実起動テスト（demoバックエンド・torch不要）。

子プロセスとして tools/local_upscale_server.py を起動→RUNNING到達→実POSTで2倍確認→
stop。共通ライフサイクル(_BaseServerManager)を通すので、着色側の無回帰も裏付ける。
ColorServerManager のエラー経路/エンドポイントも確認。直接実行可。
"""
import os
import io
import sys
import time
import socket
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PIL import Image

app = QApplication(sys.argv)

import ai_server

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def pump(predicate, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.03)
    return False


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]; s.close(); return p


def main():
    M = ai_server.UpscaleServerManager
    mgr = ai_server.get_upscale_manager()
    check(isinstance(mgr, M), "get_upscale_manager: 単一インスタンス")

    port = free_port()
    mgr.start(python=sys.executable, port=port, backend="demo", scale=2)
    ok = pump(lambda: mgr.is_running() or mgr.status == M.ERROR)
    check(ok and mgr.is_running(), f"demoサーバ起動→RUNNING 実status={mgr.status}/{mgr.message}")
    check(mgr.endpoint() == f"http://127.0.0.1:{port}/upscale", "endpoint: /upscale 導出")

    if mgr.is_running():
        # 実POST（multipart）で2倍確認
        raw = io.BytesIO(); Image.new("RGB", (100, 140), (10, 20, 30)).save(raw, "PNG")
        boundary = "----t"
        body = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="image"; filename="p.png"\r\n'
                "Content-Type: image/png\r\n\r\n").encode() + raw.getvalue() + \
               f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(mgr.endpoint(), data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = Image.open(io.BytesIO(r.read()))
        check(out.size == (200, 280), f"管理サーバへ実POST→2倍(200x280) 実={out.size}")

    mgr.stop()
    check(mgr.status == M.STOPPED and mgr.endpoint() == "", "stop: 停止しエンドポイント空")

    # ColorServerManager: エンドポイント種別＋存在しないパスでエラー
    C = ai_server.ColorServerManager
    cmgr = ai_server.get_manager()
    check(isinstance(cmgr, C), "get_manager: 着色マネージャ")
    cmgr.start(python="___no_such_python___", repo="___no_such_repo___")
    check(cmgr.status == C.ERROR, "着色: 不正パスでERROR（共通チェック経路）")

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
