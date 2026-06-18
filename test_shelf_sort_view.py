"""LibraryView の本棚ごとソート連動テスト（offscreen）。

棚を切り替えると refresh→_load_shelf_sort で並び順が復元され、_set_sort で
その棚に保存されることを確認。実データには触れない。直接実行可。
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import config

TMP = Path(tempfile.mkdtemp(prefix="piewer_shelfsort_view_"))
config.LIBRARY_FILE = TMP / "library.json"
config.SETTINGS_FILE = TMP / "settings.json"

from library_view import LibraryView

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def main():
    lib = config.Library()
    lib.shelves = [{"id": "A", "name": "A", "books": []},
                   {"id": "B", "name": "B", "books": []}]
    lib.active_shelf_id = "A"; lib.shelf_sorts = {}; lib.save()
    settings = config.Settings()

    view = LibraryView(lib, settings)

    # 棚Aで title に設定 → 保存される
    view._set_sort("title")
    check(lib.get_shelf_sort("A") == "title", "棚Aで _set_sort('title') が保存される")
    check(view._sort_mode == "title", "棚Aの _sort_mode=title")

    # 棚Bへ切替 → refresh で B の既定(added)が読み込まれる
    lib.active_shelf_id = "B"
    view.refresh()
    check(view._sort_mode == "added", "棚Bに切替で added に復元")

    # 棚Bで series に設定
    view._set_sort("series")
    check(lib.get_shelf_sort("B") == "series", "棚Bで series 保存")

    # 棚Aに戻す → title が復元
    lib.active_shelf_id = "A"
    view.refresh()
    check(view._sort_mode == "title", "棚Aに戻すと title が復元")

    # 棚Bに戻す → series が復元
    lib.active_shelf_id = "B"
    view.refresh()
    check(view._sort_mode == "series", "棚Bに戻すと series が復元")

    # 同じ棚での通常 refresh は並び順を変えない
    view._sort_mode = "progress"; view._sort_shelf_id = "B"  # 一時的に変える
    view.refresh()
    check(view._sort_mode == "progress", "同一棚の refresh では並び順を保持")

    view.deleteLater()
    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
