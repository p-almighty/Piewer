import sys
import hashlib
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QStackedWidget,
                               QStatusBar, QMessageBox, QFileDialog,
                               QDialog, QHBoxLayout, QLabel, QPushButton)
from PySide6.QtCore import (Qt, QTimer, QEvent, QUrl, QPoint,
                            QPropertyAnimation, QEasingCurve, QRect)
from PySide6.QtGui import QIcon, QDesktopServices, QCursor

import i18n
from i18n import t
import updater
import config
from config import (Library, Settings, PageSource, APP_STYLE, APP_VERSION,
                    SUPPORT_URL, RAR_SUPPORT, PDF_SUPPORT)
from widgets import TitleBar, show_global_settings
from shelf_view import ShelfSelectView
from folder_view import FolderBrowserView
from library_view import LibraryView
from reader import ReaderView


# ── Windows ネイティブフレーム ─────────────────────────────────────────
# 見た目はフレームレスのまま、OSにウィンドウ枠を認識させて Aero Snap
# （画面端ドラッグでの分割表示）・ネイティブ最大化・スナップレイアウトを有効化する。
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    from ctypes.wintypes import MSG

    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MINMAXINFO(ctypes.Structure):
        _fields_ = [("ptReserved", _POINT), ("ptMaxSize", _POINT),
                    ("ptMaxPosition", _POINT), ("ptMinTrackSize", _POINT),
                    ("ptMaxTrackSize", _POINT)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

    class _MARGINS(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    _LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    _GetWindowLong = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
    _SetWindowLong = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    _GetWindowLong.restype = _LONG_PTR
    _GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
    _SetWindowLong.restype = _LONG_PTR
    _SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    _GWL_STYLE = -16
    _WS_CAPTION = 0x00C00000
    _WS_THICKFRAME = 0x00040000
    _WS_MAXIMIZEBOX = 0x00010000
    _WS_MINIMIZEBOX = 0x00020000
    _WS_SYSMENU = 0x00080000
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOZORDER = 0x0004
    _SWP_FRAMECHANGED = 0x0020
    _MONITOR_DEFAULTTONEAREST = 2
    # WM_NCHITTEST の戻り値
    _HTCAPTION = 2
    _HTLEFT = 10; _HTRIGHT = 11; _HTTOP = 12; _HTTOPLEFT = 13; _HTTOPRIGHT = 14
    _HTBOTTOM = 15; _HTBOTTOMLEFT = 16; _HTBOTTOMRIGHT = 17


def resource_path(name: str) -> str:
    """開発時もPyInstallerバンドル時も正しいリソースパスを返す。"""
    base = getattr(sys, "_MEIPASS", str(Path(__file__).parent))
    return str(Path(base) / name)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.settings = Settings()
        if not self.settings.lang:   # 初回はOSロケールから判定（日本語以外は英語）
            from PySide6.QtCore import QLocale
            self.settings.lang = "ja" if QLocale().language() == QLocale.Language.Japanese else "en"
            self.settings.save()
        i18n.set_lang(self.settings.lang)
        self.library = Library()        # 完全無料・無制限（登録上限なし）
        self._scroll_pos = 0; self._last_book_id = ""
        self._quick_session = False  # 登録せずに開いた本を読んでいるか（戻り先を本棚選択にする）
        self._browser_session = False  # フォルダ閲覧から開いたか（戻り先をフォルダ閲覧にする）
        # 最大化・スナップは Windows ネイティブに任せる。全画面のみ自前管理。
        self._fullscreen = False
        self._pre_fs_max = False     # 全画面に入る前に最大化していたか
        self._fs_return_geom = None  # 全画面を抜けて通常状態へ戻るときの矩形
        self._geo_anim = None        # 全画面アニメーション
        self._fs_timer = None        # 全画面中のタイトルバー自動表示ポーリング
        self._native_frame_done = False

        self._setup_ui()
        QApplication.instance().installEventFilter(self)   # マウス進む/戻るボタン用

    def open_support(self):
        """寄付（開発を支援）ページを開く。完全無料・任意の支援。"""
        QDesktopServices.openUrl(QUrl(SUPPORT_URL))

    def open_global_settings(self, parent=None):
        show_global_settings(self, parent)

    def _setup_ui(self):
        self.setWindowTitle("Piewer")
        ico = resource_path("piewer.ico")
        if Path(ico).exists():
            self.setWindowIcon(QIcon(ico))
        self.resize(1100, 750)
        self.setStyleSheet("background:#18151f;")

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0); central_layout.setSpacing(0)
        self._central_layout = central_layout   # 全画面解除時にタイトルバーを戻すために保持
        self._title_bar = TitleBar(self)
        central_layout.addWidget(self._title_bar)

        self.stack = QStackedWidget()
        central_layout.addWidget(self.stack)
        self.setCentralWidget(central)

        self.shelf_select = ShelfSelectView(self.library)
        self.shelf_select.shelf_selected.connect(self._enter_shelf)
        self.shelf_select.search_requested.connect(self._enter_search)
        self.shelf_select.quick_open_requested.connect(self._quick_open)
        self.shelf_select.register_requested.connect(self._register_to_shelf)
        self.shelf_select.browse_requested.connect(self._open_folder_browser)
        self.shelf_select.random_requested.connect(self._open_random_all)

        self.folder_view = FolderBrowserView(self.settings)
        self.folder_view.open_requested.connect(self._open_from_browser)
        self.folder_view.go_home.connect(self._go_home)

        self.library_view = LibraryView(self.library, self.settings)
        self.library_view.open_book.connect(self._open_book)
        self.library_view.go_home.connect(self._go_home)

        self.reader_view = ReaderView(self.settings)
        self.reader_view.back_requested.connect(self._back_to_library)
        self.reader_view.bookmark_changed.connect(self.library.set_bookmarks)
        self.reader_view.view_changed.connect(self.library.set_view)

        self.stack.addWidget(self.shelf_select)
        self.stack.addWidget(self.folder_view)
        self.stack.addWidget(self.library_view)
        self.stack.addWidget(self.reader_view)

        self.status = QStatusBar()
        self.status.setStyleSheet("background:#1f1a29;color:#666;font-size:11px;")
        self.setStatusBar(self.status)

        self.stack.setCurrentWidget(self.shelf_select)
        self.shelf_select.refresh()
        # アップデートチェッカ（メインスレッド所属の永続オブジェクト）
        self._updater = updater.UpdateChecker(self)
        self._update_manual = False
        self._updater.finished.connect(self._on_update_result)
        # 起動後に静かにアップデート確認（新しい版があるときだけ通知）
        QTimer.singleShot(1500, lambda: self.check_for_updates(manual=False))

    def check_for_updates(self, manual: bool = False):
        self._update_manual = manual
        self._updater.start()

    def _on_update_result(self, ok: bool, ver: str, url: str, notes: str):
        manual = self._update_manual
        if ok and ver and updater.is_newer(ver):
            box = QMessageBox(self)
            box.setWindowTitle(t("アップデート"))
            msg = t("新しいバージョン v{v} があります。").format(v=ver)
            if notes: msg += "\n\n" + notes
            box.setText(msg)
            get = box.addButton(t("入手する"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(t("後で"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is get:
                QDesktopServices.openUrl(QUrl(url or updater.STORE_URL))
        elif manual:
            if ok:
                QMessageBox.information(self, t("アップデート"),
                                        t("最新版です（v{v}）。").format(v=APP_VERSION))
            else:
                QMessageBox.warning(self, t("アップデート"),
                                    t("アップデートの確認に失敗しました。\nネットワーク接続をご確認ください。"))

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, '_title_bar'):
            self._title_bar.set_title(title)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, '_title_bar'):
            self._title_bar.update_state_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._native_frame_done:
            self._native_frame_done = True
            self._enable_native_frame()

    def _enable_native_frame(self):
        """フレームレス外観のまま、OSにウィンドウ枠を認識させてネイティブのスナップ/最大化を有効化。"""
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        style = _GetWindowLong(hwnd, _GWL_STYLE)
        _SetWindowLong(hwnd, _GWL_STYLE,
                       style | _WS_CAPTION | _WS_THICKFRAME |
                       _WS_MAXIMIZEBOX | _WS_MINIMIZEBOX | _WS_SYSMENU)
        # DWM に「枠あり」と認識させ、影とネイティブ挙動（スナップ等）を有効化
        margins = _MARGINS(0, 0, 0, 1)
        _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                             _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                msg = MSG.from_address(int(message))
                m = msg.message
                if m == 0x0083:            # WM_NCCALCSIZE：枠を除去し全体をクライアント領域に
                    if msg.wParam:
                        return True, 0
                elif m == 0x0024:          # WM_GETMINMAXINFO：最大化サイズを作業領域に収める
                    self._fix_maximized_size(msg.lParam)
                    return True, 0
                elif m == 0x0084:          # WM_NCHITTEST：リサイズ枠 / タイトルバーのドラッグ判定
                    res = self._nc_hit_test(msg.lParam)
                    if res is not None:
                        return True, res
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _fix_maximized_size(self, lparam):
        """最大化時にウィンドウがタスクバーを覆ったり画面からはみ出さないよう作業領域に制限。"""
        hwnd = int(self.winId())
        mon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not mon:
            return
        mi = _MONITORINFO(); mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return
        work = mi.rcWork; full = mi.rcMonitor
        mmi = _MINMAXINFO.from_address(lparam)
        mmi.ptMaxPosition.x = work.left - full.left
        mmi.ptMaxPosition.y = work.top - full.top
        mmi.ptMaxSize.x = work.right - work.left
        mmi.ptMaxSize.y = work.bottom - work.top
        mmi.ptMaxTrackSize.x = work.right - work.left
        mmi.ptMaxTrackSize.y = work.bottom - work.top

    def _nc_hit_test(self, lparam):
        x = ctypes.c_int16(lparam & 0xFFFF).value
        y = ctypes.c_int16((lparam >> 16) & 0xFFFF).value
        if self._fullscreen:
            return None
        g = self.geometry()
        lx = x - g.x(); ly = y - g.y()
        w = self.width(); h = self.height(); e = 6
        # リサイズ枠（最大化中は無効）
        if not self.isMaximized():
            on_l = lx < e; on_r = lx > w - e; on_t = ly < e; on_b = ly > h - e
            if on_t and on_l: return _HTTOPLEFT
            if on_t and on_r: return _HTTOPRIGHT
            if on_b and on_l: return _HTBOTTOMLEFT
            if on_b and on_r: return _HTBOTTOMRIGHT
            if on_t: return _HTTOP
            if on_b: return _HTBOTTOM
            if on_l: return _HTLEFT
            if on_r: return _HTRIGHT
        # タイトルバーの空き領域 → HTCAPTION（OSがドラッグ・スナップ・ダブルクリック最大化を処理）
        if self._title_bar.is_caption_at(QPoint(x, y)):
            return _HTCAPTION
        return None   # それ以外はクライアント領域（子ウィジェットがマウスを受け取る）

    # ── ウィンドウ状態（最大化はネイティブ、全画面のみ自前管理）──
    def toggle_max(self):
        if self._fullscreen:
            self.exit_fullscreen()
        elif self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _scr(self):
        return self.screen() or QApplication.primaryScreen()

    def _animate_geometry(self, target, on_finish=None):
        """ウィンドウのジオメトリを target まで滑らかに変化させる（全画面の出入り用）。"""
        if self._geo_anim is not None:
            self._geo_anim.stop()
        if self.geometry() == target:
            if on_finish: on_finish()
            return
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(200)
        anim.setStartValue(self.geometry())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_finish:
            anim.finished.connect(on_finish)
        self._geo_anim = anim
        anim.start()

    def toggle_fullscreen(self):
        if self._fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if self._fullscreen:
            return
        self._pre_fs_max = self.isMaximized()        # 抜けたとき最大化へ戻すため記憶
        self._fullscreen = True
        self._title_bar.enter_overlay(self)          # タイトルバーをオーバーレイ化して隠す
        rv = self.reader_view
        if self.stack.currentWidget() is rv:
            rv._fs_btn.set_checked(True, silent=True)
        self._start_fs_watch()
        if self._pre_fs_max:
            self.showFullScreen()                    # 最大化中はアニメせず即全画面（状態操作が不安定なため）
        else:
            self._fs_return_geom = self.geometry()   # 戻り先を記憶し、モニタ全体へ広げてから全画面
            self._animate_geometry(QRect(self._scr().geometry()), on_finish=self._after_enter_fs)

    def _after_enter_fs(self):
        if self._fullscreen:
            self.showFullScreen()

    def exit_fullscreen(self):
        if not self._fullscreen:
            return
        self._fullscreen = False
        self._stop_fs_watch()
        self._title_bar.exit_overlay(self)           # タイトルバーをレイアウトへ戻す
        rv = self.reader_view
        if self.stack.currentWidget() is rv:
            rv._fs_btn.set_checked(False, silent=True)
            rv._set_hud_visible(True)
        if self._pre_fs_max:
            self.showMaximized()                     # 最大化へ戻す（アニメ無し）
        else:
            self.showNormal()
            self.setGeometry(self._scr().geometry()) # 見た目を一旦フルのまま保ってから縮める
            if self._fs_return_geom is not None:
                self._animate_geometry(QRect(self._fs_return_geom))
        self._title_bar.update_state_buttons()

    # ── 全画面中：マウスを最上部に寄せるとタイトルバーを表示 ──
    def _start_fs_watch(self):
        if self._fs_timer is None:
            self._fs_timer = QTimer(self)
            self._fs_timer.setInterval(80)
            self._fs_timer.timeout.connect(self._check_titlebar_reveal)
        self._fs_timer.start()

    def _stop_fs_watch(self):
        if self._fs_timer is not None:
            self._fs_timer.stop()

    def _check_titlebar_reveal(self):
        if not self._fullscreen:
            self._stop_fs_watch(); return
        tb = self._title_bar
        y = self.mapFromGlobal(QCursor.pos()).y()
        if not tb._revealed:
            if 0 <= y <= 2:
                tb.reveal_overlay(self)
        elif y > tb.height() + 6:
            tb.hide_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 全画面オーバーレイ中はタイトルバーの幅をウィンドウ幅に追従させる
        if self._fullscreen and getattr(self._title_bar, "_overlay", False):
            tb = self._title_bar
            tb.setGeometry(0, tb.y(), self.width(), tb.height())

    def retranslate_ui(self):
        """言語切替時に常設UIを即座に再翻訳する。"""
        self._title_bar.retranslate()
        self.library_view.retranslate()
        self.reader_view.retranslate()
        self.shelf_select.retranslate()
        self.folder_view.retranslate()
        cur = self.stack.currentWidget()
        if cur is self.library_view:
            shelf = self.library.current_shelf
            self.setWindowTitle(f"Piewer — {t(shelf['name'])}")
            self.status.showMessage(t("「{name}」 — {n} 冊").format(
                name=t(shelf['name']), n=len(shelf['books'])))

    def _go_home(self):
        # 本棚を離れる前に現在のスクロール位置を記憶
        if self.stack.currentWidget() is self.library_view:
            self.library_view.remember_scroll()
        self.shelf_select.refresh()
        self.stack.setCurrentWidget(self.shelf_select)
        self.setWindowTitle("Piewer")

    def _enter_shelf(self, shelf_id: str):
        self.library.switch_shelf(shelf_id)
        self.library_view.exit_search_all_mode()   # 全棚横断モードを解除してこの棚を表示
        self.library_view.refresh()
        self.library_view.apply_open_scroll()   # 設定に応じて前回位置 or 最上部
        self.stack.setCurrentWidget(self.library_view)
        self.setWindowTitle(f"Piewer — {t(self.library.current_shelf['name'])}")
        self.status.showMessage(t("「{name}」 — {n} 冊").format(
            name=t(self.library.current_shelf['name']), n=len(self.library.books)))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                cur = self.stack.currentWidget()
                if cur is self.reader_view:
                    # グリッド目次を開いていれば、まず目次を閉じて漫画表示に戻る
                    if self.reader_view.is_grid_open():
                        self.reader_view._close_grid(); return True
                    self._back_to_library(); return True
                if cur is self.library_view:
                    # 絞り込み中なら、まず絞り込みを解除（本棚一覧へは戻らない）
                    if self.library_view.has_active_filter():
                        self.library_view.clear_filters(); return True
                    self._go_home(); return True
            if event.button() == Qt.MouseButton.ForwardButton:
                if self.stack.currentWidget() is self.library_view and self._last_book_id:
                    self._open_book(self._last_book_id); return True
        return False

    # ── 全本棚を横断検索 / 登録せずに開く（クイックオープン）──────────────

    def _enter_search(self):
        """本棚選択画面の「🔍 全本棚を検索」：全棚横断検索モードで本棚ビューを開く。"""
        if self.library.is_virtual_active and self.library.shelves:
            self.library.switch_shelf(self.library.shelves[0]["id"])
        self.library_view.enter_search_all()
        self.stack.setCurrentWidget(self.library_view)
        self.setWindowTitle(f"Piewer — {t('検索')}")
        self.status.showMessage(t("全本棚を検索"))

    def _browse_one(self) -> str:
        exts = "*.cbz *.zip *.epub *.kepub *.kepub.epub"
        if RAR_SUPPORT: exts += " *.cbr *.rar"
        if PDF_SUPPORT: exts += " *.pdf"
        filters = t("漫画ファイル ({exts});;すべて (*)").format(exts=exts)
        path, _ = QFileDialog.getOpenFileName(self, t("登録せずに開く"), "", filters)
        return path

    def _quick_open(self, path: str = "", from_browser: bool = False):
        """登録せずに1冊だけ開く（ボタン＝ファイル選択 / D&D＝指定パス / フォルダ閲覧）。"""
        self._browser_session = bool(from_browser)   # 戻り先（フォルダ閲覧 or 本棚一覧）
        if not path:
            path = self._browse_one()
            if not path: return
        rp = str(Path(path).resolve())
        if not Path(rp).exists():
            QMessageBox.warning(self, t("エラー"),
                                t("ファイルが見つかりません:\n{path}").format(path=rp)); return
        # すでに登録済みの本なら通常どおり開く（進捗・しおりも保存される）
        existing = self.library.find_by_path(rp)
        if existing:
            self._browser_session = False   # 登録済みは本棚へ戻す
            self._open_book(existing["id"]); return
        try:
            source = PageSource(rp)
            if len(source) == 0:
                QMessageBox.warning(self, t("エラー"), t("読み込める画像がありません。")); return
        except Exception as e:
            QMessageBox.critical(self, t("エラー"), t("読み込み失敗:\n{e}").format(e=e)); return
        book = {"id": hashlib.md5(rp.encode()).hexdigest(), "title": Path(rp).stem,
                "path": rp, "last_page": 0, "total_pages": 0, "cover_cache": "",
                "bookmarks": [], "favorite": False, "tags": [], "view": {}}
        self._quick_session = True
        self.reader_view.load_book(book, source, start_page=0)
        self.stack.setCurrentWidget(self.reader_view)
        self.reader_view.setFocus()
        self.setWindowTitle(f"Piewer - {book['title']}")

    def _open_random_all(self):
        """本棚一覧の「🎲 ランダム」：全本棚を横断してランダムに1冊開く。"""
        import random
        pairs = [(s["id"], b["id"]) for s in self.library.shelves for b in s["books"]]
        if not pairs:
            QMessageBox.information(self, t("ランダム"), t("本が登録されていません。"))
            return
        sid, bid = random.choice(pairs)
        # その本の本棚へ切り替えてから開く（戻り先がその本棚になる）
        self.library.switch_shelf(sid)
        self.library_view.refresh()
        self._open_book(bid)

    def _import_folder_shelves(self):
        """フォルダ構成から本棚を一括生成（サブフォルダ＝本棚）。"""
        d = QFileDialog.getExistingDirectory(self, t("本棚にするフォルダ（の親）を選択"))
        if not d:
            return
        created, added = self.library.import_folders_as_shelves(d)
        if created:
            self.shelf_select.refresh()
            QMessageBox.information(self, t("完了"),
                t("{s} 個の本棚に {b} 冊を取り込みました。").format(s=created, b=added))
        else:
            QMessageBox.information(self, t("完了"),
                t("取り込める本棚（サブフォルダ）が見つかりませんでした。"))

    def _open_folder_browser(self):
        """本棚選択画面の「📁 フォルダから開く」：エクスプローラ式ブラウザを表示。"""
        self._browser_session = False
        self.stack.setCurrentWidget(self.folder_view)
        self.folder_view.reveal_last()
        self.setWindowTitle(f"Piewer — {t('フォルダから開く')}")

    def _open_from_browser(self, path: str):
        """フォルダ閲覧から開く＝登録せず開き、戻り先をフォルダ閲覧にする。"""
        self._quick_open(path, from_browser=True)

    def _register_to_shelf(self, shelf_id: str, paths: list):
        """本棚選択画面で通常の本棚カードへD&D → その本棚に登録する。"""
        self.library.switch_shelf(shelf_id)
        self.library_view._add_paths(paths)   # 重複・上限ダイアログ込み
        self.shelf_select.refresh()            # 各カードの冊数表示を更新

    def _open_book(self, book_id: str):
        self._quick_session = False
        book = self.library.get(book_id)
        if not book: return
        if not Path(book["path"]).exists():
            QMessageBox.warning(self, t("エラー"),
                                t("ファイルが見つかりません:\n{path}").format(path=book['path'])); return
        try:
            source = PageSource(book["path"])
            if len(source) == 0:
                QMessageBox.warning(self, t("エラー"), t("読み込める画像がありません。")); return
        except Exception as e:
            QMessageBox.critical(self, t("エラー"), t("読み込み失敗:\n{e}").format(e=e)); return

        # RAR は一覧はできても展開ツールが無いと中身を読めない（圧縮/RAR5）。
        # 無言でブランク表示になるのを避け、原因を伝える。
        if getattr(source, "_type", "") == "rar" and not config.rar_tool_ready():
            QMessageBox.warning(self, t("エラー"),
                t("このRARを開くには展開ツールが必要ですが、見つかりませんでした。\n"
                  "Piewer同梱の unrar が読み込めていない可能性があります。\n"
                  "（ZIP/CBZ形式に変換すると確実に開けます）")); return

        start_page = 0
        last = book.get("last_page", 0)
        if last > 0:
            mode = getattr(self.settings, "resume_mode", "continue")
            if mode == "ask":
                choice = self._ask_continue(book)
                if choice == "cancel": return
                start_page = last if choice == "continue" else 0
            elif mode == "start":
                start_page = 0
            else:   # "continue"（既定）＝確認せず続きから開く
                start_page = last

        # 履歴棚から開いた本は履歴順を更新しない（仕様）。通常の本棚からのみ記録。
        if not self.library.is_history_active:
            self.library.record_history(book_id)
        self._scroll_pos = self.library_view.save_scroll_pos()
        self._last_book_id = book_id
        self.reader_view.load_book(book, source, start_page=start_page)
        self.stack.setCurrentWidget(self.reader_view)
        self.reader_view.setFocus()
        self.setWindowTitle(f"Piewer - {book['title']}")

    def _ask_continue(self, book: dict) -> str:
        # QMessageBox はWindowsのシステム音が鳴るため、音の出ないカスタムダイアログを使う
        dlg = QDialog(self)
        dlg.setWindowTitle(book["title"])
        dlg.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:14px; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:8px 18px; font-size:13px; min-width:120px; }
            QPushButton:hover { background:#423a5a; border-color:#a06cff; }
            QPushButton#primary { background:#a06cff; color:white; border:none; }
            QPushButton#primary:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(22, 20, 22, 16); lay.setSpacing(16)
        lay.addWidget(QLabel(t("どこから読みますか？")))
        result = {"v": "cancel"}
        row = QHBoxLayout(); row.setSpacing(8); row.addStretch()
        cont = QPushButton(t("続きから読む")); cont.setObjectName("primary"); cont.setDefault(True)
        fresh = QPushButton(t("最初から読む"))
        cancel = QPushButton(t("キャンセル"))
        cont.clicked.connect(lambda: (result.update(v="continue"), dlg.accept()))
        fresh.clicked.connect(lambda: (result.update(v="fresh"), dlg.accept()))
        cancel.clicked.connect(dlg.reject)
        for b in (cancel, fresh, cont):
            b.setCursor(Qt.CursorShape.PointingHandCursor); row.addWidget(b)
        lay.addLayout(row)
        dlg.exec()
        return result["v"]

    def _back_to_library(self):
        # 全画面表示はそのまま維持して本棚へ戻る（Esc /「← 本棚」/ マウス戻る 共通）。
        if self.reader_view.book_id:
            self.library.update_progress(self.reader_view.book_id,
                                          self.reader_view.get_current_page(),
                                          self.reader_view.get_total_pages())
        if self._quick_session:
            # 登録せずに開いた本は元の画面へ戻す（フォルダ閲覧から開いたなら閲覧へ）
            self._quick_session = False
            if self._browser_session:
                self._browser_session = False
                self._open_folder_browser(); return
            self._go_home(); return
        self.stack.setCurrentWidget(self.library_view)
        self.library_view.refresh()
        self.library_view.restore_scroll_pos(self._scroll_pos)
        shelf = self.library.current_shelf
        self.setWindowTitle(f"Piewer — {t(shelf['name'])}")
        self.status.showMessage(t("「{name}」 — {n} 冊").format(
            name=t(shelf['name']), n=len(shelf['books'])))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Piewer")
    ico = resource_path("piewer.ico")
    if Path(ico).exists():
        app.setWindowIcon(QIcon(ico))
    import theme
    _st = Settings()
    theme.set_accent(getattr(_st, "accent", "violet"))          # 設定のアクセント色を適用
    theme.set_theme(getattr(_st, "theme", "dark"))              # ダーク/ライト
    theme.install_theming()                                     # setStyleSheet をフック
    app.setStyleSheet(theme.themed(APP_STYLE))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
