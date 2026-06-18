"""本棚ごとの並び順（shelf_sorts）の保存/復元テスト。

LIBRARY_FILE を一時dirへ隔離。実データ(~/.manga_viewer)には触れない。直接実行可。
"""
import sys
import json
import tempfile
from pathlib import Path

import config

TMP = Path(tempfile.mkdtemp(prefix="piewer_shelfsort_"))
config.LIBRARY_FILE = TMP / "library.json"

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def fresh_library_with_two_shelves():
    lib = config.Library()
    lib.shelves = [{"id": "A", "name": "A", "books": []},
                   {"id": "B", "name": "B", "books": []}]
    lib.active_shelf_id = "A"
    lib.shelf_sorts = {}
    lib.save()
    return lib


def main():
    lib = fresh_library_with_two_shelves()

    # 既定は "added"
    check(lib.get_shelf_sort("A") == "added", "未設定は既定 added")

    # 棚ごとに別の並び順を保存
    lib.set_shelf_sort("A", "title")
    lib.set_shelf_sort("B", "series")
    check(lib.get_shelf_sort("A") == "title", "A=title 保存")
    check(lib.get_shelf_sort("B") == "series", "B=series 保存")
    check(lib.get_shelf_sort("C") == "added", "未知の棚は added")

    # 既定 "added" にするとキーを持たない（ファイルを軽く保つ）
    lib.set_shelf_sort("A", "added")
    check("A" not in lib.shelf_sorts, "added に戻すとキー削除")
    check(lib.get_shelf_sort("A") == "added", "削除後は added 既定")

    # ファイルに永続化されている
    raw = json.loads(config.LIBRARY_FILE.read_text(encoding="utf-8"))
    check(raw.get("shelf_sorts", {}).get("B") == "series", "JSONに shelf_sorts 保存")
    check("A" not in raw.get("shelf_sorts", {}), "JSONに既定キーは無い")

    # 別インスタンスで読み直して復元
    lib2 = config.Library()
    check(lib2.get_shelf_sort("B") == "series", "再ロードで B=series 復元")
    check(lib2.get_shelf_sort("A") == "added", "再ロードで A=added")

    # 仮想棚IDでも保存できる（履歴等）
    lib2.set_shelf_sort(config.HISTORY_ID, "recent")
    check(lib2.get_shelf_sort(config.HISTORY_ID) == "recent", "仮想棚(履歴)の並び順も保存")

    # 棚を削除すると並び順の記憶も消える
    lib2.set_shelf_sort("B", "title")
    lib2.delete_shelf("B")
    check("B" not in lib2.shelf_sorts, "delete_shelf で並び順も掃除")

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
