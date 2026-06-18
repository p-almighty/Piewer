"""ガイド付きUX（ワンボタン）＋ ImageFxダイアログ統合のオフスクリーンテスト。

ネット非依存（ai_runtime.cugan_ready をモックして download を回避）。
実データに触れない。直接実行可。
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import config
import ai_upscale
import ai_runtime
import plugins

TMP = Path(tempfile.mkdtemp(prefix="piewer_upscale_ux_"))
config.SETTINGS_FILE = TMP / "settings.json"
ai_upscale.CACHE_DIR = TMP / "ai_upscale"
# ネットを避ける: 準備済み扱いにして download をスキップさせる
ai_runtime.cugan_ready = lambda scale=2, denoise=1: True

from widgets import AiUpscaleDialog, ImageFxDialog

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


class FakeReader:
    def __init__(self):
        self.applied = 0
    def apply_ai_upscale(self):
        self.applied += 1


def main():
    plugins.discover(force=True)
    settings = config.Settings()
    reader = FakeReader()

    dlg = AiUpscaleDialog(settings, on_change=reader.apply_ai_upscale, reader=reader)

    # 主要ウィジェットが揃う（ガイド構成）
    for attr in ("_scale_cb", "_dev_cb", "_setup_btn", "_status_lbl", "_on_cb",
                 "_adv_btn", "_adv", "_endpoint", "_plugin_cb"):
        check(hasattr(dlg, attr), f"ウィジェット存在: {attr}")

    # 詳細設定は既定で隠れている → トグルで開く（offscreenでは isHidden で判定）
    check(dlg._adv.isHidden() is True, "詳細設定は既定で非表示")
    dlg._adv_btn.setChecked(True); dlg._toggle_adv()
    check(dlg._adv.isHidden() is False, "詳細設定: トグルで表示")

    # ワンボタン: 自動セットアップ（cugan_ready=Trueなのでダウンロードはスキップ）
    dlg._scale_cb.setCurrentIndex(dlg._scale_cb.findData(4))
    dlg._dev_cb.setCurrentIndex(dlg._dev_cb.findData("cuda"))
    dlg._auto_setup()

    au = settings.ai_upscale
    check(au.get("on") is True, "auto_setup: on=True 保存")
    check(au.get("server", {}).get("manage") is True, "auto_setup: manage=True 保存")
    check(au.get("server", {}).get("scale") == 4, "auto_setup: scale=4 保存")
    check(au.get("server", {}).get("device") == "cuda", "auto_setup: device=cuda 保存")
    check(au.get("plugin") == "local_upscale", "auto_setup: plugin 保存")
    check(reader.applied >= 1, "auto_setup: reader.apply_ai_upscale が呼ばれた")
    check(dlg._on_cb.isChecked(), "auto_setup: 有効チェックON")
    # 接続先は manage で自動導出
    check(au.get("opts", {}).get("endpoint") == "http://127.0.0.1:7861/upscale",
          "auto_setup: 接続先を自動導出")
    # 状態ラベルが何か表示している
    check(bool(dlg._status_lbl.text()), "状態ラベルに表示あり")

    # 無効トグル
    dlg._on_cb.setChecked(False)
    check(settings.ai_upscale.get("on") is False, "トグルOFF: on=False 保存")

    dlg.close()

    # ── ImageFxダイアログに AI超解像の入口がある ──
    settings.ai_upscale = {"on": True, "plugin": "local_upscale",
                           "opts": {"endpoint": "http://x"}, "server": {}}
    fx = ImageFxDialog(settings, reader=reader)
    check(hasattr(fx, "_up_open_btn"), "ImageFx: AI超解像を開くボタンがある")
    check(fx._up_state_lbl.text() == "有効", f"ImageFx: 有効状態を表示 実='{fx._up_state_lbl.text()}'")
    settings.ai_upscale = {"on": False}
    fx._refresh_upscale_state()
    check(fx._up_state_lbl.text() == "無効", "ImageFx: 無効状態を表示")
    fx.close()

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
