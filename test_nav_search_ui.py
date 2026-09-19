"""マウス戻る/進むの統一・検索モード表示・検索クリアボタン・本一覧の中央揃え（offscreen）。

実データ（~/.manga_viewer）には触らず一時ディレクトリを使う。直接実行可。
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

import config

TMP = Path(tempfile.mkdtemp(prefix="piewer_nav_ui_"))
config.LIBRARY_FILE = TMP / "library.json"
config.SETTINGS_FILE = TMP / "settings.json"
config.COVERS_DIR = TMP / "covers"

from library_view import LibraryView
import manga_viewer

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def make_lib():
    lib = config.Library()
    lib.shelves = [{"id": "A", "name": "棚A", "books": [
                       {"id": "b1", "title": "本1", "path": str(TMP / "b1.cbz"), "cover_cache": ""},
                       {"id": "b2", "title": "本2", "path": str(TMP / "b2.cbz"), "cover_cache": ""}]},
                   {"id": "B", "name": "棚B", "books": [
                       {"id": "b3", "title": "本3", "path": str(TMP / "b3.cbz"), "cover_cache": ""}]}]
    lib.active_shelf_id = "A"; lib.shelf_sorts = {}; lib.history = []; lib.save()
    return lib


def test_view():
    lib = make_lib(); settings = config.Settings()
    view = LibraryView(lib, settings)
    view.resize(1000, 700)
    view.refresh()

    # ── 検索窓の✕ボタン
    check(view._search_clear.isHidden(), "クリアボタンは入力が空なら非表示")
    view._search_box.setText("本")
    check(not view._search_clear.isHidden(), "文字を入れるとクリアボタンが出る")
    check(view._search_clear.x() + view._search_clear.width() <= view._search_box.width(),
          "クリアボタンは検索窓の内側（右寄せ）")
    # 入力の再描画はまとめる（打っている間は refresh しない）
    check(view._search_timer.isActive(), "入力中はデバウンスタイマーが動く")
    view.refresh()
    check(not view._search_timer.isActive(), "refresh で保留中の再描画を消化する")
    check(len(view._all_books) == 2, "検索結果が入力に追従する（本1/本2）")
    view._clear_search()
    check(view._search_box.text() == "" and view._filter == "",
          "クリアで入力と絞り込みが消える")
    check(view._search_clear.isHidden(), "クリア後はクリアボタンが消える")

    # ── 戻るボタンで検索文字列も1段階として解除できる
    view._search_box.setText("本1")
    check(view.has_active_filter(), "検索文字列があれば has_active_filter=True")
    view.clear_filters()
    check(view._search_box.text() == "" and not view.has_active_filter(),
          "clear_filters で検索文字列も消える")

    # ── 検索モードの表示：棚名ではなく「全本棚を検索」
    check(not view.is_search_all_mode(), "初期は検索モードではない")
    view.enter_search_all()
    check(view.is_search_all_mode(), "enter_search_all で検索モード")
    check("検索" in view._shelf_name_lbl.text(), "ヘッダが検索表示（棚名ではない）")
    check("棚A" not in view._shelf_name_lbl.text(), "ヘッダに棚名を出さない")
    check(not view._addfile_btn._enabled_look, "検索中は「+ ファイル」が無効表示")
    check(not view._settings_btn._enabled_look, "検索中は「⚙ 設定」が無効表示")
    check(len(view._all_books) == 3, "検索モードは全本棚の本を集める")
    view.exit_search_all_mode(); view.refresh()
    check("棚A" in view._shelf_name_lbl.text(), "検索解除で棚名が戻る")
    check(view._addfile_btn._enabled_look, "検索解除で「+ ファイル」が有効に戻る")
    check(view._settings_btn._enabled_look, "検索解除で「⚙ 設定」が有効に戻る")

    # ── 本一覧の中央揃え
    view.resize(1000, 700)
    view.refresh()
    cw = settings.cover_w
    cols = view._v_cols
    grid_w = cols * (cw + 4) + max(0, cols - 1) * config.CARD_SPACING
    vp = view.scroll.viewport().width()
    left = view._v_x0
    right = vp - (left + grid_w)
    check(abs(left - right) <= 1 or left == view._MARGIN,
          f"左右の余白がほぼ均等（left={left} right={right} vp={vp} cols={cols}）")
    check(left >= view._MARGIN, "左マージンは最低16px確保")
    view.deleteLater()
    return lib


def test_nav():
    lib = make_lib()
    win = manga_viewer.MainWindow()
    win.library.shelves = lib.shelves
    win.library.active_shelf_id = "A"
    win.library.save()
    win.library_view.refresh()

    # 本棚 → 本棚一覧 → 進むで同じ本棚へ
    win._enter_shelf("B")
    check(win.stack.currentWidget() is win.library_view, "棚Bを開ける")
    win._go_home()
    check(win.stack.currentWidget() is win.shelf_select, "戻るで本棚一覧へ")
    check(win._fwd_state == ("shelf", "B"), f"直前の棚を記憶（{win._fwd_state}）")
    check(win._go_forward(), "本棚一覧で進むが効く")
    check(win.stack.currentWidget() is win.library_view and win.library.active_shelf_id == "B",
          "進むで棚Bに戻る")

    # 検索モード → 戻る → 進むで検索モードに戻る
    win._enter_search()
    check(win.library_view.is_search_all_mode(), "検索モードで開く")
    win.library_view._search_box.setText("本")
    win._go_home()
    check(win._fwd_state == ("search", ""), "検索モードを記憶")
    check(win._go_forward() and win.library_view.is_search_all_mode(),
          "進むで検索モードに戻る")
    check(win.library_view._search_box.text() == "本", "進むで検索語も復元")
    win._go_home(); win._enter_search()
    check(win.library_view._search_box.text() == "", "検索ボタンから入り直すと空で始まる")

    # フォルダ閲覧 → 戻る → 進む
    win._open_folder_browser()
    win._go_home()
    check(win._fwd_state == ("folder", ""), "フォルダ閲覧を記憶")
    check(win._go_forward() and win.stack.currentWidget() is win.folder_view,
          "進むでフォルダ閲覧に戻る")

    # 消えた本棚は進む対象にしない
    win._go_home()
    win._enter_shelf("B"); win._go_home()
    win.library.shelves = [s for s in win.library.shelves if s["id"] != "B"]
    check(not win._go_forward(), "削除された本棚へは進まない")
    check(win._fwd_state is None, "無効な記憶は捨てる")

    # 進む対象が無い状態では何もしない
    check(not win._go_forward(), "記憶が無ければ進むは無効")
    win.close(); win.deleteLater()


def main():
    test_view()
    test_nav()
    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
