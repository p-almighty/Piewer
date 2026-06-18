"""AiUpscaleDialog のオフスクリーンUIスモーク＋demoサーバ接続テスト。

実データに触れない（settings/キャッシュを一時dirへ）。dialogの生成・設定保存・
接続テスト（demoサーバへ実POST）を確認する。直接実行可。
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

app = QApplication(sys.argv)

import config
import ai_upscale
import plugins

TMP = Path(tempfile.mkdtemp(prefix="piewer_upscale_ui_"))
config.SETTINGS_FILE = TMP / "settings.json"
ai_upscale.CACHE_DIR = TMP / "ai_upscale"

# demoサーバをモジュールとして読み込み起動
_spec = importlib.util.spec_from_file_location(
    "local_upscale_server", Path(__file__).parent / "tools" / "local_upscale_server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)

from widgets import AiUpscaleDialog

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def pump(predicate, timeout=5.0):
    """predicate() が真になるまでイベントループを回す。"""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def main():
    plugins.discover(force=True)
    check(plugins.get_upscaler("local_upscale") is not None,
          "前提: local_upscale プラグイン検出")

    # demoサーバ起動（2倍）
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(srv.DemoBackend(scale=2)))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{port}/upscale"

    settings = config.Settings()
    changed = {"n": 0}

    dlg = AiUpscaleDialog(settings, on_change=lambda: changed.__setitem__("n", changed["n"] + 1))
    try:
        # プラグインが選ばれている
        check(dlg._plugin_cb.currentData() == "local_upscale", "ダイアログ: プラグイン自動選択")

        # 設定: 有効化 + endpoint + 4x
        dlg._endpoint.setText(endpoint)
        dlg._on_cb.setChecked(True)           # stateChanged→_apply
        si = dlg._scale_cb.findData(4); dlg._scale_cb.setCurrentIndex(si)  # →_apply
        dlg._persist()

        au = settings.ai_upscale
        check(au.get("on") is True, "保存: on=True")
        check(au.get("plugin") == "local_upscale", "保存: plugin")
        check(au.get("opts", {}).get("endpoint") == endpoint, "保存: endpoint")
        check(au.get("server", {}).get("scale") == 4, "保存: scale=4")
        check(changed["n"] >= 1, "on_change が呼ばれた")

        # 再ロードで復元される
        s2 = config.Settings()
        check(s2.ai_upscale.get("opts", {}).get("endpoint") == endpoint,
              "再ロード: endpoint 復元")

        # 接続テスト（demoサーバへ実POST）
        dlg._test()
        ok = pump(lambda: dlg._test_lbl.text().startswith(("✓", "✗")))
        check(ok and dlg._test_lbl.text().startswith("✓"),
              f"接続テスト成功表示 実='{dlg._test_lbl.text()}'")

        # サーバ自動管理: manage ON で接続先がポートから自動導出＋読み取り専用
        dlg._manage_cb.setChecked(True)   # stateChanged→_on_manage_changed→_apply
        check(dlg._endpoint.text() == "http://127.0.0.1:7861/upscale",
              f"manage ON: 接続先を自動導出 実='{dlg._endpoint.text()}'")
        check(dlg._endpoint.isReadOnly(), "manage ON: 接続先は読み取り専用")
        dlg._dev_cb.setCurrentIndex(dlg._dev_cb.findData("cuda")); dlg._persist()
        sv = settings.ai_upscale.get("server", {})
        check(sv.get("manage") is True, "保存: server.manage=True")
        check(sv.get("device") == "cuda", "保存: server.device=cuda")
        # manage OFF に戻すと手入力可能
        dlg._manage_cb.setChecked(False)
        check(not dlg._endpoint.isReadOnly(), "manage OFF: 接続先を手入力できる")
    finally:
        httpd.shutdown()
        dlg.close()

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
