# updater.py — オンラインのバージョン情報を確認するだけの軽量アップデートチェッカー。
#
# 公開リポジトリに置いた latest.json を取得し、新しいバージョンがあれば
# GitHub のリリースページ（無料ダウンロード）へ誘導する。
#
# 実装メモ: QRunnable + 自前 QObject シグナルは PySide6 で寿命競合のクラッシュを
# 起こしやすい。ここでは「メインスレッドに属する永続 QObject」＋「デーモンスレッド」
# で行い、ワーカーからは finished をキューイング送信する（安全な定石）。

import json
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

from config import APP_VERSION
import i18n

# 公開リポジトリの raw に置く版情報。形式:
#   {"version": "1.6", "url": "https://github.com/p-almighty/Piewer/releases/latest",
#    "notes_ja": "・〇〇を追加", "notes_en": "- Added ..."}
MANIFEST_URL = "https://raw.githubusercontent.com/p-almighty/Piewer/main/latest.json"
STORE_URL = "https://github.com/p-almighty/Piewer/releases/latest"   # GitHub Releases（無料DL）


def _ver_tuple(s: str) -> tuple:
    out = []
    for p in str(s).split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _ver_tuple(remote) > _ver_tuple(local)


class UpdateChecker(QObject):
    """メインスレッドに属する永続オブジェクト。start() でバックグラウンド取得。"""
    finished = Signal(bool, str, str, str)   # (ok, latest_version, url, notes)

    def start(self, timeout: float = 6.0):
        threading.Thread(target=self._run, args=(timeout,), daemon=True).start()

    def _run(self, timeout: float):
        try:
            req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "Piewer"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ver = str(data.get("version", "")).strip()
            url = str(data.get("url", "")).strip() or STORE_URL
            notes = data.get("notes_en" if i18n.get_lang() == "en" else "notes_ja", "")
            self.finished.emit(True, ver, url, str(notes))
        except Exception:
            self.finished.emit(False, "", "", "")
