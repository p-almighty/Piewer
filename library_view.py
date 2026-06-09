import re
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFileDialog, QMessageBox, QInputDialog, QLineEdit, QDialog,
    QPushButton, QTextEdit, QApplication, QMenu, QScroller
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPoint, QElapsedTimer
from PySide6.QtGui import QPixmap, QCursor, QPainter, QColor, QPainterPath

from config import (Library, Settings, current_covers_dir, CARD_SPACING,
                    RAR_SUPPORT, PDF_SUPPORT, COVER_EXT, export_backup, import_backup,
                    RECENT_ID, CONTINUE_ID)
from image_utils import CoverWorker
from widgets import (FlatBtn, ToggleBtn, BookCard, TagEditDialog, TagPopup,
                     TagManagerDialog, TagFilterDialog, make_fold_completer, fold_text)
from i18n import t

from PySide6.QtCore import QThreadPool


class LibraryView(QWidget):
    open_book = Signal(str)
    go_home   = Signal()

    _MARGIN = 16
    _BUFFER = 2

    def __init__(self, library: Library, settings: Settings, parent=None):
        super().__init__(parent)
        self.library = library; self.settings = settings
        self.cards: dict[str, BookCard] = {}
        self.pool = QThreadPool.globalInstance()
        self._sort_mode = "added"; self._filter = ""
        self._search_all = False            # 全本棚を横断検索
        self._fav_filter = False            # ★お気に入りのみ表示
        self._tag_filter: set[str] = set()  # 選択中のタグ
        self._tag_match = "or"              # タグ一致: "or"=いずれか / "and"=すべて
        self._read_filter = "all"           # 読書状態: "all" / "unread" / "read"
        self._selection_mode = False; self._selected_ids: set[str] = set()
        self._sel_anchor_id: str | None = None  # Shift範囲選択の起点
        self._mid_mode = False; self._mid_origin = QPoint()
        self._drag_pos = None          # マウスドラッグスクロールの押下位置(global)
        self._drag_scrolling = False
        self._drag_press_val = 0
        # ドラッグ後の慣性スクロール（フリック）
        self._fling_v = 0.0; self._fling_pos = 0.0
        self._drag_last_val = 0; self._drag_last_ms = 0
        self._drag_clock = QElapsedTimer(); self._drag_clock.start()
        self._fling_timer = QTimer(self)
        self._fling_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._fling_timer.setInterval(16)
        self._fling_timer.timeout.connect(self._fling_tick)
        self._mid_timer = QTimer(self); self._mid_timer.setInterval(16)
        self._mid_timer.timeout.connect(self._mid_tick)
        self._scroll_cursor = self._make_scroll_cursor()
        self._all_books: list[dict] = []
        self._v_cols = 1
        self._v_card_w = 160; self._v_card_h = 220
        self._v_row_h = 0
        self._v_cards: dict[str, tuple] = {}
        self._scroll_target: float = 0.0
        self._scroll_pos_f: float = 0.0   # サブピクセル精度の現在位置（高Hzで滑らかに）
        self._shelf_scroll: dict[str, int] = {}   # 本棚IDごとの最後のスクロール位置
        self._cover_loading: set[str] = set()
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._smooth_timer.timeout.connect(self._scroll_tick)
        self._apply_fps()  # ウィンドウのあるモニターのリフレッシュレートを反映
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120); self._resize_timer.timeout.connect(self.refresh)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background:#18151f;")
        self.setAcceptDrops(True)   # ファイルのドラッグ&ドロップで追加
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        tb_w = QWidget(); tb_w.setFixedHeight(50)
        tb_w.setStyleSheet("background:#1f1a29;border-bottom:1px solid #2b2539;")
        tb = QHBoxLayout(tb_w); tb.setContentsMargins(10, 8, 10, 8); tb.setSpacing(6)

        self._tr = []   # 言語切替で再翻訳する (widget, 原文, 種別)

        def fb(jp, cb, blue=False):
            b = FlatBtn(t(jp), h=32, blue=blue); b.set_callback(cb)
            self._tr.append((b, jp, "text")); return b

        tb.addWidget(fb("⌂ 本棚一覧", self.go_home.emit))
        self._shelf_name_lbl = QLabel("")
        self._shelf_name_lbl.setStyleSheet("color:#ddd;font-size:14px;font-weight:bold;margin:0 8px;")
        # 棚名の文字数でツールバーがズレないよう固定幅。長い名前は…で省略（全文はツールチップ）。
        self._shelf_name_lbl.setFixedWidth(168)
        tb.addWidget(self._shelf_name_lbl)
        tb.addSpacing(8)
        self._addfile_btn = fb("+ ファイル", self._add_files, blue=True)
        tb.addWidget(self._addfile_btn)
        tb.addSpacing(6)

        self._sort_btn = fb("並び替え ▾", self._show_sort_menu)  # 表示は _set_sort が上書き
        tb.addWidget(self._sort_btn)
        tb.addSpacing(6)

        size_lbl = QLabel(t("サイズ:"), styleSheet="color:#888;font-size:11px;")
        self._tr.append((size_lbl, "サイズ:", "text"))
        tb.addWidget(size_lbl)
        self._sz_s = ToggleBtn(t("小"), self.settings.thumb_size == "small",  h=30)
        self._sz_m = ToggleBtn(t("中"), self.settings.thumb_size == "medium", h=30)
        self._sz_l = ToggleBtn(t("大"), self.settings.thumb_size == "large",  h=30)
        self._sz_s.set_callback(lambda _: self._set_size("small"))
        self._sz_m.set_callback(lambda _: self._set_size("medium"))
        self._sz_l.set_callback(lambda _: self._set_size("large"))
        self._tr += [(self._sz_s, "小", "text"), (self._sz_m, "中", "text"), (self._sz_l, "大", "text")]
        tb.addWidget(self._sz_s); tb.addWidget(self._sz_m); tb.addWidget(self._sz_l)
        tb.addSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(t("🔍 検索..."))
        self._tr.append((self._search_box, "🔍 検索...", "placeholder"))
        self._search_box.setFixedSize(150, 30)
        self._search_box.setStyleSheet("QLineEdit{background:#2b2539;color:#ddd;border:1px solid #463d63;border-radius:10px;padding:0 8px;font-size:12px;} QLineEdit:focus{border-color:#a06cff;}")
        self._search_box.textChanged.connect(self._on_search)
        tb.addWidget(self._search_box)
        self._search_all_btn = ToggleBtn(t("全棚"), False, h=30)
        self._search_all_btn.setToolTip(t("全ての本棚を横断して検索"))
        self._search_all_btn.set_callback(self._on_search_all)
        self._tr += [(self._search_all_btn, "全棚", "text"),
                     (self._search_all_btn, "全ての本棚を横断して検索", "tooltip")]
        tb.addWidget(self._search_all_btn)
        tb.addSpacing(6)
        self._filter_btn = fb("🏷 絞り込み", self._show_filter_menu)  # 表示は _update_filter_btn が上書き
        tb.addWidget(self._filter_btn)
        tb.addSpacing(6)
        self._random_btn = fb("🎲 ランダム", self._open_random)
        self._random_btn.setToolTip(t("この本棚からランダムに1冊開く"))
        tb.addWidget(self._random_btn)
        tb.addStretch()

        self._sel_mode_btn = ToggleBtn(t("選択削除モード"), False, h=30)
        self._sel_mode_btn.set_callback(self._toggle_sel_mode)
        self._tr.append((self._sel_mode_btn, "選択削除モード", "text"))
        tb.addWidget(self._sel_mode_btn)
        tb.addSpacing(6)
        # ⚙ 設定は画面の一番右（選択削除モードの右隣）に配置
        self._settings_btn = fb("⚙ 設定", self._open_settings)
        tb.addWidget(self._settings_btn)
        root.addWidget(tb_w)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{border:none;background:#18151f;}")
        # 幅14px：通常ウィンドウ時の右端リサイズ枠(6px)に食われても内側を掴める太さを確保
        self.scroll.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical{background:#18151f;width:14px;} "
            "QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;} "
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self._grid_w = QWidget(); self._grid_w.setStyleSheet("background:#18151f;")
        # 空の本棚に表示する大きな追加プロンプト（クリックでファイル追加）
        self._empty_lbl = QLabel(t("＋\n\nここをクリックして漫画を追加"), self._grid_w)
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_normal_style = ("QLabel{color:#a18fd0;font-size:20px;font-weight:bold;"
                                    "background:#221d31;border:3px dashed #5a4a8c;border-radius:16px;}"
                                    " QLabel:hover{color:#c9b6ff;border-color:#a06cff;background:#2a2440;}")
        self._empty_hist_style = "QLabel{color:#463d63;font-size:18px;background:transparent;}"
        self._empty_lbl.setStyleSheet(self._empty_normal_style)
        self._empty_lbl.setVisible(False)
        self._empty_lbl.mousePressEvent = self._on_empty_clicked
        self.scroll.setWidget(self._grid_w)
        self.scroll.viewport().installEventFilter(self)
        # タッチは慣性スクロール（QScroller）。マウスドラッグは eventFilter で処理。
        QScroller.grabGesture(self.scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value)
        root.addWidget(self.scroll)

        self._sel_bar = QWidget(); self._sel_bar.setFixedHeight(44)
        self._sel_bar.setStyleSheet("background:#241d33;border-top:1px solid #a06cff;")
        sl = QHBoxLayout(self._sel_bar); sl.setContentsMargins(12, 6, 12, 6); sl.setSpacing(8)
        self._sel_count_lbl = QLabel(t("{n} 冊選択中").format(n=0))
        self._sel_count_lbl.setStyleSheet("color:#aaa;font-size:12px;")
        sl.addWidget(self._sel_count_lbl); sl.addStretch()
        for key, cb, bl in [("全選択", self._select_all, False),
                            ("全解除", self._deselect_all, False),
                            ("別の本棚へ移動", self._move_selected, False),
                            ("選択した本を削除", self._delete_selected, True)]:
            b = FlatBtn(t(key), h=30, blue=bl); b.set_callback(cb); sl.addWidget(b)
            self._tr.append((b, key, "text"))
            if key == "別の本棚へ移動": self._move_sel_btn = b
        self._sel_bar.setVisible(False)
        root.addWidget(self._sel_bar)

    def _detect_fps(self) -> float:
        """ウィンドウが今表示されているモニターのリフレッシュレートを取得。"""
        scr = self.screen() or QApplication.primaryScreen()
        rate = scr.refreshRate() if scr else 60.0
        return max(30.0, min(500.0, rate or 60.0))

    def _apply_fps(self):
        """リフレッシュレートに合わせてタイマー間隔とイージング係数を設定。"""
        fps = self._detect_fps()
        self._fps = fps
        # フレームレートに依存せず一定の滑らかさ（約フレーム数ぶんで収束）になるよう正規化
        self._smooth_alpha = 1.0 - (0.55 ** (60.0 / fps))
        self._smooth_timer.setInterval(max(2, round(1000.0 / fps)))  # 360Hz→約3ms

    def _scroll_tick(self):
        bar = self.scroll.verticalScrollBar()
        diff = self._scroll_target - self._scroll_pos_f
        if abs(diff) < 0.5:
            self._scroll_pos_f = self._scroll_target
            bar.setValue(round(self._scroll_target))
            self._smooth_timer.stop()
            return
        # サブピクセル精度で位置を進め、描画時のみ整数化（高Hzでも滑らか）
        self._scroll_pos_f += diff * self._smooth_alpha
        bar.setValue(round(self._scroll_pos_f))

    def _fling_tick(self):
        bar = self.scroll.verticalScrollBar()
        self._fling_pos += self._fling_v
        mn, mx = bar.minimum(), bar.maximum()
        if self._fling_pos <= mn or self._fling_pos >= mx:
            self._fling_pos = max(mn, min(mx, self._fling_pos))
            bar.setValue(round(self._fling_pos)); self._fling_timer.stop()
        else:
            bar.setValue(round(self._fling_pos))
            self._fling_v *= 0.90          # 摩擦による減速
            if abs(self._fling_v) < 0.4:
                self._fling_timer.stop()
        self._scroll_target = float(bar.value()); self._scroll_pos_f = float(bar.value())

    def _on_scroll_value(self, _: int):
        self._update_visible_cards()

    def _update_visible_cards(self):
        if not self._all_books: return
        M = self._MARGIN; BUF = self._BUFFER
        cw, ch = self._v_card_w, self._v_card_h
        cols = self._v_cols; row_h = self._v_row_h
        if row_h <= 0: return
        scroll_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        start_row = max(0, (scroll_y - M) // row_h - BUF)
        end_row = min((scroll_y + vp_h - M) // row_h + BUF, (len(self._all_books) - 1) // cols)
        start_i = start_row * cols
        end_i = min((end_row + 1) * cols, len(self._all_books))
        vis = set(range(start_i, end_i))
        gone = [bid for bid, (_, idx) in self._v_cards.items() if idx not in vis]
        for bid in gone:
            card, _ = self._v_cards.pop(bid)
            self.cards.pop(bid, None)
            card.hide(); card.deleteLater()
        for i in vis:
            book = self._all_books[i]
            bid = book["id"]
            if bid in self._v_cards: continue
            card = BookCard(book, cw, ch, parent=self._grid_w)
            row, col = i // cols, i % cols
            card.move(M + col * (cw + 4 + CARD_SPACING), M + row * row_h)
            card.show()
            card.clicked.connect(self.open_book.emit)
            card.remove_requested.connect(self._remove_one)
            card.selection_toggled.connect(self._on_card_sel)
            card.menu_requested.connect(self._show_card_menu)
            card.favorite_clicked.connect(self._on_favorite_clicked)
            card.tags_clicked.connect(self._show_tags_popup)
            card.installEventFilter(self)
            if self._selection_mode:
                card.set_selection_mode(True)
                if bid in self._selected_ids: card.set_selected(True)
            self._v_cards[bid] = (card, i)
            self.cards[bid] = card
            cp = book.get("cover_cache", "")
            if cp and Path(cp).exists():
                card.set_cover(QPixmap(cp))
            elif bid not in self._cover_loading:
                self._cover_loading.add(bid)
                w = CoverWorker(book); w.signals.finished.connect(self._on_cover)
                self.pool.start(w)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.Wheel and not self._mid_mode:
            dy = event.angleDelta().y()
            if dy != 0:
                self._fling_timer.stop()   # 慣性スクロール中のホイールは慣性を止める
                bar = self.scroll.verticalScrollBar()
                # 新しいスクロール開始時は実位置へ再同期＋モニターのHzを再判定
                if not self._smooth_timer.isActive():
                    self._scroll_pos_f = float(bar.value())
                    self._scroll_target = float(bar.value())
                    self._apply_fps()
                row_h = self._v_row_h if self._v_row_h > 0 else (self._v_card_h + 4 + CARD_SPACING)
                amount = (dy / 120.0) * row_h
                self._scroll_target = max(float(bar.minimum()),
                                          min(float(bar.maximum()), self._scroll_target - amount))
                self._smooth_timer.start()
                return True
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            if self._mid_mode:
                self._stop_mid()
            else:
                self._fling_timer.stop()
                self._mid_origin = self.scroll.viewport().mapFromGlobal(QCursor.pos())
                self._mid_mode = True
                self.scroll.viewport().setCursor(self._scroll_cursor)
                self._mid_timer.start()
            return True
        if t == QEvent.Type.MouseButtonPress and self._mid_mode:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                self._stop_mid(); return True
        # ── 左ドラッグでスクロール（カードのクリック判定と両立）──
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton \
                and not self._mid_mode:
            self._fling_timer.stop(); self._fling_v = 0.0
            self._drag_pos = event.globalPosition().toPoint()
            self._drag_scrolling = False
            self._drag_press_val = self.scroll.verticalScrollBar().value()
            self._drag_last_val = self._drag_press_val
            self._drag_last_ms = self._drag_clock.elapsed()
            return False   # 押下はカードへ通す（タップ＝クリックを生かす）
        if t == QEvent.Type.MouseMove and self._drag_pos is not None \
                and (event.buttons() & Qt.MouseButton.LeftButton):
            dy = event.globalPosition().toPoint().y() - self._drag_pos.y()
            if not self._drag_scrolling and abs(dy) > 8:
                self._drag_scrolling = True
                self._smooth_timer.stop()
            if self._drag_scrolling:
                bar = self.scroll.verticalScrollBar()
                bar.setValue(self._drag_press_val - dy)
                actual = bar.value()
                # 直近の移動量から速度（px/tick相当）を推定
                delta = actual - self._drag_last_val
                self._fling_v = 0.55 * self._fling_v + 0.45 * delta
                self._drag_last_val = actual
                self._drag_last_ms = self._drag_clock.elapsed()
                self._scroll_target = float(actual); self._scroll_pos_f = float(actual)
                return True   # スクロール中はカードへ渡さない（誤クリック防止）
            return False
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton \
                and self._drag_pos is not None:
            was = self._drag_scrolling
            self._drag_pos = None; self._drag_scrolling = False
            if was:
                # 離す直前に動いていて十分な速度があれば慣性で滑らせる
                idle = self._drag_clock.elapsed() - self._drag_last_ms
                if idle <= 60 and abs(self._fling_v) >= 1.5:
                    self._fling_pos = float(self.scroll.verticalScrollBar().value())
                    self._fling_timer.start()
                return True   # ドラッグスクロールだったのでクリックさせない
        return False

    def _mid_tick(self):
        if not self._mid_mode: self._mid_timer.stop(); return
        cur = self.scroll.viewport().mapFromGlobal(QCursor.pos())
        dy = cur.y() - self._mid_origin.y(); dead = 12
        if abs(dy) > dead:
            speed = (abs(dy) - dead) * 0.35 * (1 if dy > 0 else -1)
            bar = self.scroll.verticalScrollBar()
            bar.setValue(int(bar.value() + speed))
            self._scroll_target = float(bar.value())

    def _stop_mid(self):
        self._mid_mode = False; self._mid_timer.stop()
        self.scroll.viewport().unsetCursor()

    def _make_scroll_cursor(self) -> QCursor:
        sz = 32
        pm = QPixmap(sz, sz); pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = sz // 2, sz // 2, 11
        p.setPen(QColor(0, 0, 0, 160)); p.setBrush(QColor(240, 240, 240, 220))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(60, 60, 60, 255))
        p.drawEllipse(cx - 2, cy - 2, 4, 4)
        pu = QPainterPath()
        pu.moveTo(cx, cy - r + 3); pu.lineTo(cx - 4, cy - 5); pu.lineTo(cx + 4, cy - 5)
        pu.closeSubpath()
        pd = QPainterPath()
        pd.moveTo(cx, cy + r - 3); pd.lineTo(cx - 4, cy + 5); pd.lineTo(cx + 4, cy + 5)
        pd.closeSubpath()
        p.fillPath(pu, QColor(60, 60, 60, 255)); p.fillPath(pd, QColor(60, 60, 60, 255))
        p.end()
        return QCursor(pm, cx, cy)

    SORT_LABELS = {"added": "登録順", "title": "ファイル名",
                   "recent": "最近読んだ順", "progress": "進捗順", "series": "シリーズ順"}

    # シリーズの巻数マーカー（第N巻 / N巻 / vol.N / v.N / 末尾(N) / #N / N話）
    _VOL_RE = re.compile(
        r"(?:第\s*(\d+)\s*巻|(\d+)\s*巻|vol\.?\s*(\d+)|v\.?\s*(\d+)"
        r"|[（(](\d+)[)）]\s*$|#\s*(\d+)|(\d+)\s*話)", re.I)

    def _series_key(self, book):
        """同シリーズを巻順に隣接させる並び替えキー（base, 巻番号, タイトル）。"""
        title = book.get("title", "")
        base = title; vol = 0
        m = self._VOL_RE.search(title)
        if m:
            for g in m.groups():
                if g:
                    vol = int(g); break
            base = title[:m.start()].strip()
        else:
            m2 = re.search(r"[（(]?([上中下])[)）]?\s*$", title)
            if m2:
                vol = {"上": 1, "中": 2, "下": 3}[m2.group(1)]
                base = title[:m2.start()].strip()
        return (fold_text(base.strip(" 　-_‐~〜")), vol, fold_text(title))

    def _show_sort_menu(self):
        menu = QMenu(self); menu.setStyleSheet(self._MENU_QSS)
        acts = {}
        for mode, label in self.SORT_LABELS.items():
            a = menu.addAction(("● " if mode == self._sort_mode else "　") + t(label))
            acts[a] = mode
        chosen = menu.exec(self._sort_btn.mapToGlobal(self._sort_btn.rect().bottomLeft()))
        if chosen in acts:
            self._set_sort(acts[chosen])

    def _set_sort(self, mode: str):
        self._sort_mode = mode
        self._sort_btn.setText(t("並び替え: {label} ▾").format(label=t(self.SORT_LABELS.get(mode, ''))))
        self.refresh()

    def _on_search(self, text: str):
        self._filter = fold_text(text); self.refresh()   # かな/全半角を区別しない

    def _on_search_all(self, checked: bool):
        self._search_all = checked; self.refresh()

    @staticmethod
    def _progress_of(b: dict) -> int:
        total = b.get("total_pages", 0)
        return int(b.get("last_page", 0) / total * 100) if total > 0 else 0

    def _set_size(self, size: str):
        self.settings.thumb_size = size; self.settings.save()
        self._sz_s.set_checked(size == "small",  silent=True)
        self._sz_m.set_checked(size == "medium", silent=True)
        self._sz_l.set_checked(size == "large",  silent=True)
        self.refresh()

    def enter_search_all(self):
        """全本棚を横断して検索するモードで開く（本棚選択画面の検索ボタン用）。"""
        self._search_all = True
        self._search_all_btn.set_checked(True, silent=True)
        self._search_box.clear()
        self.refresh()
        self._search_box.setFocus()

    def exit_search_all_mode(self):
        """通常の本棚を開くときは全棚横断モードを解除する（その棚だけを表示）。"""
        self._search_all = False
        self._search_all_btn.set_checked(False, silent=True)

    def _sorted_books(self) -> list[dict]:
        # 全棚横断検索が有効なときは全実棚から集める（重複ID除去）。
        # テキスト未入力でも全本棚の本を一覧表示する。
        if self._search_all:
            seen = set(); books = []
            for s in self.library.shelves:
                for b in s["books"]:
                    if b["id"] not in seen:
                        seen.add(b["id"]); books.append(b)
        else:
            books = list(self.library.books)
        if self._sort_mode == "title":
            books.sort(key=lambda b: b["title"].lower())
        elif self._sort_mode == "recent":
            books.sort(key=lambda b: b.get("last_opened", ""), reverse=True)
        elif self._sort_mode == "progress":
            books.sort(key=self._progress_of, reverse=True)
        elif self._sort_mode == "series":
            books.sort(key=self._series_key)
        if self._filter: books = [b for b in books if self._filter in fold_text(b["title"])]
        if self._fav_filter:
            books = [b for b in books if b.get("favorite", False)]
        rf = getattr(self, "_read_filter", "all")
        if rf == "unread":
            books = [b for b in books if not b.get("last_opened")]
        elif rf == "read":
            books = [b for b in books if b.get("last_opened")]
        if self._tag_filter:
            if getattr(self, "_tag_match", "or") == "and":   # すべてのタグを含む
                books = [b for b in books if self._tag_filter <= set(b.get("tags", []))]
            else:                                            # いずれかのタグを含む
                books = [b for b in books if self._tag_filter & set(b.get("tags", []))]
        return books

    _MENU_QSS = ("QMenu{background:#262032;color:#ddd;} "
                 "QMenu::item:selected{background:#a06cff;} "
                 "QMenu::item:disabled{color:#777;}")

    # ── 絞り込み（お気に入り / タグ）────────────────────────

    def _sync_search_suggest(self):
        """検索窓のサジェストを現在の本棚のタイトルで更新（かな/全半角一致）。

        絞り込み中（self.library.books は変わらない）はタイトル集合が同じなので
        作り直さず、入力中の補完を妨げない。
        """
        titles = tuple(sorted({b["title"] for b in self.library.books}))
        if titles == getattr(self, "_suggest_sig", None):
            return
        self._suggest_sig = titles
        old = self._search_box.completer()
        self._search_box.setCompleter(make_fold_completer(titles, self))
        if old is not None:
            old.deleteLater()   # 旧コンプリータ(とモデル)を破棄してリーク防止

    def _open_random(self):
        """今表示中の本（絞り込み/検索が効いていればその中）からランダムに1冊開く。"""
        import random
        books = self._all_books
        if not books:
            return
        self.open_book.emit(random.choice(books)["id"])

    def _show_filter_menu(self):
        # タグが多数でも検索・スクロールできるダイアログで絞り込む。
        # 開閉状態とスクロール位置は前回を引き継ぐ（毎回上から畳まれて戻らないように）。
        dlg = TagFilterDialog(self.library.all_tags(), self._tag_filter, self._fav_filter, self,
                              expanded=getattr(self, "_tagfilter_expanded", None),
                              scroll=getattr(self, "_tagfilter_scroll", 0),
                              read_state=self._read_filter, tag_match=self._tag_match,
                              labels=self.settings.effective_tag_labels())
        ok = dlg.exec()
        self._tagfilter_expanded = dlg.current_expanded()   # 次回のために記憶
        self._tagfilter_scroll = dlg.current_scroll()
        if ok:
            self._fav_filter = dlg.result_fav
            self._tag_filter = set(dlg.result_tags)
            self._read_filter = dlg.result_read
            self._tag_match = dlg.result_match
            self._update_filter_btn(); self.refresh()

    def _update_filter_btn(self):
        read_on = self._read_filter != "all"
        active = self._fav_filter or bool(self._tag_filter) or read_on
        n = (1 if self._fav_filter else 0) + len(self._tag_filter) + (1 if read_on else 0)
        self._filter_btn.setText(t("🏷 絞り込み ({n})").format(n=n) if active else t("🏷 絞り込み"))
        if active:
            self._filter_btn.setStyleSheet(
                "QLabel{background:#a06cff;color:white;border-radius:10px;padding:0 10px;"
                "font-size:12px;} QLabel:hover{background:#b488ff;}")
        else:
            self._filter_btn.setStyleSheet(
                "QLabel{background:#2b2539;color:#ccc;border-radius:10px;padding:0 10px;"
                "font-size:12px;} QLabel:hover{background:#393350;}")

    def retranslate(self):
        """言語切替時にツールバー等の文言を貼り替える。"""
        for w, jp, kind in self._tr:
            if kind == "text": w.setText(t(jp))
            elif kind == "tooltip": w.setToolTip(t(jp))
            elif kind == "placeholder": w.setPlaceholderText(t(jp))
        # 動的に変わるもの
        self._set_sort(self._sort_mode)      # 並び替えボタン（ラベル＋再描画）
        self._update_filter_btn()
        self._update_sel_count()

    def has_active_filter(self) -> bool:
        return self._fav_filter or bool(self._tag_filter) or self._read_filter != "all"

    def clear_filters(self):
        self._fav_filter = False; self._tag_filter.clear()
        self._read_filter = "all"
        self._update_filter_btn(); self.refresh()

    # ── 本カードの右クリックメニュー ────────────────────────

    def _real_shelf_id_of(self, bid: str) -> str | None:
        for s in self.library.shelves:
            if any(b["id"] == bid for b in s["books"]):
                return s["id"]
        return None

    def _show_card_menu(self, bid: str, gpos):
        book = self.library.get(bid)
        if not book: return
        hist = self.library.is_history_active
        menu = QMenu(self); menu.setStyleSheet(self._MENU_QSS)
        fav = bool(book.get("favorite", False))
        fav_act  = menu.addAction(t("★ お気に入りを解除") if fav else t("☆ お気に入りに追加"))
        is_read = bool(book.get("last_opened"))
        read_act = menu.addAction(t("📕 未読に戻す") if is_read else t("📗 既読にする"))
        tags_act = menu.addAction(t("🏷 タグを編集…"))
        move_menu = menu.addMenu(t("📁 別の本棚へ移動"))
        move_menu.setStyleSheet(self._MENU_QSS)
        move_targets = {}
        cur_real = self._real_shelf_id_of(bid)
        targets = [s for s in self.library.shelves if s["id"] != cur_real]
        if targets:
            for s in targets:
                a = move_menu.addAction(s["name"]); move_targets[a] = s["id"]
        else:
            a = move_menu.addAction(t("（他に本棚がありません）")); a.setEnabled(False)
        menu.addSeparator()
        if self.library.is_favorites_active:
            del_label = t("お気に入りから外す")
        elif hist:
            del_label = t("履歴から削除")
        else:
            del_label = t("本棚から削除")
        del_act = menu.addAction(del_label)
        chosen = menu.exec(gpos)
        if chosen is None: return
        if chosen is fav_act:
            new = self.library.toggle_favorite(bid)
            card = self.cards.get(bid)
            if card: card.set_favorite(new)
            if self._fav_filter or self.library.is_favorites_active: self.refresh()
        elif chosen is read_act:
            self.library.set_read_state(bid, not is_read)
            self.refresh()
        elif chosen is tags_act:
            self._edit_tags(bid)
        elif chosen is del_act:
            self._remove_one(bid)
        elif chosen in move_targets:
            if self.library.move_book(bid, move_targets[chosen]):
                self.refresh()

    def _show_tags_popup(self, bid: str, gpos):
        """カード左上のタグアイコンクリック：付いているタグを一覧表示。
        タグ名クリックで絞り込みトグル、「✕」でその本からタグを解除。"""
        book = self.library.get(bid)
        if not book: return
        tags = book.get("tags", [])
        if not tags: return
        popup = TagPopup(tags, self._tag_filter, self)
        popup.filter_toggled.connect(self._toggle_tag_filter)
        popup.tag_removed.connect(lambda t, b=bid: self._remove_tag_from_book(b, t))
        popup.edit_requested.connect(lambda b=bid, p=popup: (p.close(), self._edit_tags(b)))
        self._tag_popup = popup   # GC回避のため参照を保持
        popup.move(gpos); popup.show()

    def _toggle_tag_filter(self, tag: str):
        self._tag_filter.discard(tag) if tag in self._tag_filter else self._tag_filter.add(tag)
        self._update_filter_btn(); self.refresh()

    def _remove_tag_from_book(self, bid: str, tag: str):
        book = self.library.get(bid)
        if not book: return
        new = [x for x in book.get("tags", []) if x != tag]
        self.library.set_tags(bid, new)
        card = self.cards.get(bid)
        if card: card.set_tags(new)
        if tag in self._tag_filter and tag not in self.library.all_tags():
            self._tag_filter.discard(tag); self._update_filter_btn()
        self.refresh()

    def _on_favorite_clicked(self, bid: str):
        new = self.library.toggle_favorite(bid)
        card = self.cards.get(bid)
        if card: card.set_favorite(new)
        # お気に入り絞り込み中・お気に入り棚では、外れた本を消すため再描画
        if self._fav_filter or self.library.is_favorites_active:
            self.refresh()

    def _edit_tags(self, bid: str):
        book = self.library.get(bid)
        if not book: return
        dlg = TagEditDialog(book.get("tags", []), self.library.all_tags(), self)
        if not dlg.exec():
            return
        tags = dlg.result_tags()
        self.library.set_tags(bid, tags)
        card = self.cards.get(bid)
        if card: card.set_tags(tags)
        if self._tag_filter:
            self._tag_filter &= set(self.library.all_tags())  # 消えたタグは絞り込みから外す
            self._update_filter_btn()
            self.refresh()

    def _move_selected(self):
        if not self._selected_ids: return
        if self.library.is_history_active:
            QMessageBox.information(self, t("移動できません"),
                                    t("履歴からは移動できません。元の本棚で操作してください。"))
            return
        targets = [s for s in self.library.shelves if s["id"] != self.library.active_shelf_id]
        if not targets:
            QMessageBox.information(self, t("移動先がありません"),
                                    t("他に本棚がありません。先に本棚を作成してください。"))
            return
        menu = QMenu(self); menu.setStyleSheet(self._MENU_QSS)
        acts = {}
        for s in targets:
            a = menu.addAction(t("「{name}」へ移動").format(name=s['name'])); acts[a] = s["id"]
        chosen = menu.exec(self._move_sel_btn.mapToGlobal(self._move_sel_btn.rect().bottomLeft()))
        if chosen in acts:
            self.library.move_many(set(self._selected_ids), acts[chosen])
            self._exit_sel_mode(); self.refresh()

    def _set_shelf_name(self, name: str):
        """棚名を固定幅ラベルに省略表示（はみ出す分は…）。全文はツールチップ。"""
        fm = self._shelf_name_lbl.fontMetrics()
        avail = max(20, self._shelf_name_lbl.width() - 18)   # margin(0 8px)分を差し引く
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, avail)
        self._shelf_name_lbl.setText(elided)
        self._shelf_name_lbl.setToolTip(name if elided != name else "")

    def _rename_current_shelf(self):
        shelf = self.library.current_shelf
        name, ok = QInputDialog.getText(self, t("名前を変更"), t("新しい名前:"), text=shelf["name"])
        if ok and name.strip():
            self.library.rename_shelf(shelf["id"], name.strip())
            self._set_shelf_name(name.strip())

    def _toggle_sel_mode(self, checked: bool):
        self._selection_mode = checked; self._sel_bar.setVisible(checked)
        if not checked: self._exit_sel_mode()
        else:
            for card in self.cards.values(): card.set_selection_mode(True)
        self._update_sel_count()

    def _exit_sel_mode(self):
        self._selection_mode = False; self._selected_ids.clear()
        self._sel_anchor_id = None
        self._sel_mode_btn.set_checked(False, silent=True); self._sel_bar.setVisible(False)
        for card in self.cards.values(): card.set_selection_mode(False)

    def _sync_card_visuals(self):
        """表示中のカードの選択表示を _selected_ids に合わせる。"""
        for bid, card in self.cards.items():
            card.set_selected(bid in self._selected_ids)

    def _on_card_sel(self, bid: str, sel: bool):
        mods = QApplication.keyboardModifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if shift and self._sel_anchor_id and self._sel_anchor_id != bid:
            # 起点から今クリックした本までの範囲をまとめて選択
            ids = [b["id"] for b in self._all_books]
            try:
                i1 = ids.index(self._sel_anchor_id); i2 = ids.index(bid)
            except ValueError:
                i1 = i2 = None
            if i1 is not None:
                lo, hi = sorted((i1, i2))
                for k in range(lo, hi + 1):
                    self._selected_ids.add(ids[k])
                self._sync_card_visuals()   # クリックで反転した表示も含めて補正
            # アンカーは維持（連続Shiftクリックで起点から伸縮できる）
        else:
            if sel: self._selected_ids.add(bid)
            else: self._selected_ids.discard(bid)
            self._sel_anchor_id = bid
        self._update_sel_count()

    def _update_sel_count(self): self._sel_count_lbl.setText(t("{n} 冊選択中").format(n=len(self._selected_ids)))

    def _select_all(self):
        for book in self._all_books: self._selected_ids.add(book["id"])
        for card in self.cards.values(): card.set_selected(True)
        self._update_sel_count()

    def _deselect_all(self):
        self._selected_ids.clear()
        self._sel_anchor_id = None
        for card in self.cards.values(): card.set_selected(False)
        self._update_sel_count()

    def _delete_selected(self):
        if not self._selected_ids: return
        n = len(self._selected_ids)
        if self.library.is_history_active:
            # 履歴棚では「履歴から削除」（本そのものは消さない）
            if QMessageBox.question(self, t("履歴から削除"),
                                    t("選択した {n} 冊を履歴から外しますか？\n（本そのものは削除されません）").format(n=n),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.library.remove_many_from_history(set(self._selected_ids)); self._exit_sel_mode(); self.refresh()
            return
        if self.library.is_favorites_active:
            # お気に入り棚では「★解除」（本そのものは消さない）
            if QMessageBox.question(self, t("お気に入りから外す"),
                                    t("選択した {n} 冊をお気に入りから外しますか？\n（本そのものは削除されません）").format(n=n),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.library.unfavorite_many(set(self._selected_ids)); self._exit_sel_mode(); self.refresh()
            return
        if self.library.active_shelf_id in (RECENT_ID, CONTINUE_ID):
            # 「最近追加」「続きを読む」は仮想棚なので、本棚から完全に削除する
            if QMessageBox.question(self, t("削除確認"),
                                    t("選択した {n} 冊を本棚から削除しますか？\n（元のファイルは削除されません）").format(n=n),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.library.remove_many_everywhere(set(self._selected_ids)); self._exit_sel_mode(); self.refresh()
            return
        if QMessageBox.question(self, t("削除確認"), t("選択した {n} 冊を削除しますか？").format(n=n),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.library.remove_many(set(self._selected_ids)); self._exit_sel_mode(); self.refresh()

    def refresh(self):
        self._stop_mid(); self._smooth_timer.stop(); self._fling_timer.stop()
        self._set_shelf_name(t(self.library.current_shelf["name"]))
        # 仮想棚（履歴・お気に入り）では「ファイル追加」を隠す
        virt = self.library.is_virtual_active
        # UIの一貫性: 仮想棚（お気に入り/履歴）でも「+ ファイル」は消さず無効表示にして
        # 位置を固定する（棚を切り替えてもツールバーのボタンがズレないようにする）。
        self._addfile_btn.set_enabled_look(not virt)
        self._addfile_btn.setToolTip(
            t("お気に入り・最近読んだ本には直接追加できません（通常の本棚に追加してください）")
            if virt else "")
        if virt and self._selection_mode:
            self._exit_sel_mode()
        self._sync_search_suggest()
        for card, _ in self._v_cards.values():
            card.hide(); card.deleteLater()
        self._v_cards.clear(); self.cards.clear()
        books = self._sorted_books()
        self._all_books = books
        if not books:
            # 本が無いときは最小高さを切り詰め、widgetResizable でビューポートに合わせる
            # （ビューポート高を焼き込まないのでスクロールは出ない・リサイズにも追従）
            self._grid_w.setMaximumHeight(16_777_215)
            self._grid_w.setMinimumHeight(1)
            gw = max(400, self._grid_w.width())
            if self.library.is_favorites_active:
                self._empty_lbl.setText(t("お気に入りの本がありません\n（本の表紙の右上「★」をクリックで登録）"))
                self._empty_lbl.setStyleSheet(self._empty_hist_style)
                self._empty_lbl.setGeometry((gw - 460) // 2, 80, 460, 60)
            elif virt:
                if self.library.active_shelf_id == CONTINUE_ID:
                    msg = t("読みかけの本はありません")
                elif self.library.active_shelf_id == RECENT_ID:
                    msg = t("まだ本が追加されていません")
                else:
                    msg = t("まだ読んだ本がありません")
                self._empty_lbl.setText(msg)
                self._empty_lbl.setStyleSheet(self._empty_hist_style)
                self._empty_lbl.setGeometry((gw - 400) // 2, 80, 400, 40)
            else:
                self._empty_lbl.setText(t("＋\n\nここをクリックして漫画を追加"))
                self._empty_lbl.setStyleSheet(self._empty_normal_style)
                bw, bh = 420, 220
                self._empty_lbl.setGeometry((gw - bw) // 2, 70, bw, bh)
            self._empty_lbl.setVisible(True); return
        self._empty_lbl.setVisible(False)
        cw, ch = self.settings.cover_w, self.settings.cover_h
        M = self._MARGIN
        avail_w = self.scroll.viewport().width() - M * 2
        cols = max(1, (avail_w + CARD_SPACING) // (cw + 4 + CARD_SPACING))
        self._v_cols = cols; self._v_card_w = cw; self._v_card_h = ch
        self._v_row_h = ch + 4 + CARD_SPACING
        total_rows = (len(books) + cols - 1) // cols
        # 最終行の後ろには行間を入れない（余分なスクロールが出るのを防ぐ）。
        # 内容がビューポートに収まる場合は widgetResizable が自動でフィットさせ、
        # スクロール不可になる（ビューポート高を焼き込まないのでリサイズにも追従）。
        content_h = M + total_rows * (ch + 4) + max(0, total_rows - 1) * CARD_SPACING + M
        vp_h = self.scroll.viewport().height()
        if content_h <= vp_h:
            # 収まる場合は最大高さもビューポート高に固定し、widgetResizable のタイミングに
            # 依存せず確実にスクロール範囲を 0 にする（収まる棚で余分にスクロールできる対策）。
            self._grid_w.setMaximumHeight(vp_h)
            self._grid_w.setMinimumHeight(content_h)
        else:
            self._grid_w.setMaximumHeight(16_777_215)   # 制限解除（あふれる分はスクロール）
            self._grid_w.setMinimumHeight(content_h)
        # widgetResizable はビューポートのサイズが変わらないと内側ウィジェットを再リサイズ
        # しない。棚を切り替えても高さが前の棚のまま残り、収まる棚なのにスクロールできる
        # （特にお気に入り／履歴で発生）のを防ぐため、高さを明示的に合わせる。
        self._grid_w.resize(self.scroll.viewport().width(), max(content_h, vp_h))
        bar = self.scroll.verticalScrollBar()
        self._scroll_target = max(float(bar.minimum()),
                                  min(float(bar.maximum()), self._scroll_target))
        self._scroll_pos_f = self._scroll_target
        self._update_visible_cards()

    def _on_cover(self, bid: str, img):
        self._cover_loading.discard(bid)
        px = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
        if bid in self._v_cards:
            self._v_cards[bid][0].set_cover(px)
        cp = current_covers_dir() / f"{bid}.{COVER_EXT}"
        if cp.exists(): self.library.set_cover(bid, str(cp))

    def _on_empty_clicked(self, e):
        # 空の本棚プロンプトのクリック（仮想棚では何もしない）
        if e.button() == Qt.MouseButton.LeftButton and not self.library.is_virtual_active:
            self._add_files()

    def _add_files(self):
        exts = "*.cbz *.zip *.epub *.kepub *.kepub.epub"
        if RAR_SUPPORT: exts += " *.cbr *.rar"
        if PDF_SUPPORT: exts += " *.pdf"
        filters = t("漫画ファイル ({exts});;すべて (*)").format(exts=exts)
        paths, _ = QFileDialog.getOpenFileNames(self, t("ファイルを追加"), "", filters)
        self._add_paths(paths)

    def _add_paths(self, paths):
        """与えられたパス群をライブラリに追加（重複はまとめて通知）。"""
        if not paths: return
        added, dups = [], []
        for p in paths:
            r = self.library.add(p, save=False)
            if r is None: dups.append(Path(p).name)
            else: added.append(r)
        if added:
            # 設定がONなら、追加した本にファイル名から自動タグ付け（実験的）
            if getattr(self.settings, "auto_tag_on_add", False):
                import auto_tag
                mapping, _ = auto_tag.propose(
                    added, {auto_tag.T_ARTIST, auto_tag.T_PARODY, auto_tag.T_EVENT},
                    labels=self.settings.effective_tag_labels())
                self.library.add_tags_bulk(mapping)
            self.library.save(); self.refresh()
        if dups: self._show_dup_dialog(dups)

    # ── ドラッグ&ドロップでの追加 ───────────────────────────

    _DND_EXT = {".cbz", ".zip", ".cbr", ".rar", ".pdf", ".epub", ".kepub"}

    def _accepts_dnd(self, event) -> bool:
        # 仮想棚（履歴・お気に入り）には追加できない
        if self.library.is_virtual_active:
            return False
        md = event.mimeData()
        if not md.hasUrls():
            return False
        return any(self._dnd_path(u) for u in md.urls())

    def _dnd_path(self, url) -> str:
        """対応形式のローカルファイル（またはフォルダ）パスなら返す。"""
        p = url.toLocalFile()
        if not p: return ""
        path = Path(p)
        if path.is_dir():
            return p
        if path.suffix.lower() in self._DND_EXT:
            return p
        return ""

    def dragEnterEvent(self, event):
        if self._accepts_dnd(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts_dnd(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self._accepts_dnd(event):
            event.ignore(); return
        paths = [self._dnd_path(u) for u in event.mimeData().urls()]
        paths = [p for p in paths if p]
        event.acceptProposedAction()
        self._add_paths(paths)

    def _show_dup_dialog(self, dups: list[str]):
        dlg = QDialog(self)
        dlg.setWindowTitle(t("重複ファイル")); dlg.setMinimumSize(540, 340)
        dlg.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; }
            QTextEdit { background:#2b2539; color:#ddd; border:1px solid #463d63;
                        border-radius:10px; font-size:12px; padding:4px; }
            QPushButton { background:#a06cff; color:white; border:none;
                          border-radius:10px; padding:6px 24px; font-size:12px; min-width:70px; }
            QPushButton:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        lay.addWidget(QLabel(t("以下の {n} 件のファイルはすでに登録されています:").format(n=len(dups))))
        text = QTextEdit(); text.setReadOnly(True); text.setPlainText("\n".join(dups))
        lay.addWidget(text)
        btn_row = QHBoxLayout(); btn_row.addStretch()
        ok_btn = QPushButton("OK"); ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn); lay.addLayout(btn_row)
        QTimer.singleShot(0, lambda: text.verticalScrollBar().setValue(text.verticalScrollBar().maximum()))
        dlg.exec()

    def _remove_one(self, bid: str):
        # 仮想棚では本体を消さない：履歴=履歴から除外、お気に入り=★解除
        if self.library.is_history_active:
            self.library.remove_from_history(bid)
        elif self.library.is_favorites_active:
            self.library.set_favorite(bid, False)
        else:
            self.library.remove(bid)
        self.refresh()

    def _regen_covers(self):
        # 旧PNG・新JPGの両方を削除して作り直す
        for pat in ("*.png", "*.jpg"):
            for f in current_covers_dir().glob(pat):
                try: f.unlink()
                except Exception: pass
        self.library.clear_all_covers(); self.refresh()

    def _check_updates(self):
        win = self.window()
        if hasattr(win, "check_for_updates"):
            win.check_for_updates(manual=True)

    def _open_tag_manager(self, parent=None):
        TagManagerDialog(self.library, self.settings, parent or self).exec()
        # 削除/改名で消えたタグを絞り込みから外す
        self._tag_filter &= set(self.library.all_tags())
        self._update_filter_btn(); self.refresh()

    def _backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("バックアップを保存"), "piewer_backup.json", t("Piewer バックアップ (*.json)"))
        if not path: return
        try:
            export_backup(path)
            QMessageBox.information(self, t("完了"), t("バックアップを保存しました:\n{path}").format(path=path))
        except Exception as e:
            QMessageBox.warning(self, t("エラー"), t("保存に失敗しました:\n{e}").format(e=e))

    def _restore(self, parent_dialog=None):
        if QMessageBox.question(
                self, t("復元の確認"),
                t("バックアップから復元すると、現在の本棚・設定は置き換わります。続けますか？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                ) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, t("バックアップを選択"), "", t("Piewer バックアップ (*.json);;すべて (*)"))
        if not path: return
        try:
            import_backup(path)
        except Exception as e:
            QMessageBox.warning(self, t("エラー"), t("復元に失敗しました:\n{e}").format(e=e)); return
        # メモリ上のデータを読み直して反映
        self.library.reload(); self.settings.reload()
        if parent_dialog is not None:
            parent_dialog.accept()
        QMessageBox.information(self, t("完了"), t("復元しました。"))
        self.go_home.emit()   # 本棚一覧へ戻して最新状態で再構築

    def _open_settings(self):
        """本棚の設定画面（名前変更・サムネイル再生成・保存先変更）。"""
        hist = self.library.is_virtual_active   # 仮想棚（履歴・お気に入り）は名前変更不可
        dlg = QDialog(self)
        dlg.setWindowTitle(t("設定"))
        dlg.setMinimumWidth(440)
        dlg.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel#title { color:#d8ccff; font-size:15px; font-weight:bold; }
            QLabel#desc { color:#888; font-size:11px; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:9px 14px; font-size:13px; text-align:left; }
            QPushButton:hover:enabled { background:#423a5a; border-color:#a06cff; }
            QPushButton:disabled { color:#666; }
            QPushButton#close { background:#a06cff; color:white; border:none;
                                text-align:center; padding:7px 24px; }
            QPushButton#close:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(20, 18, 20, 16); lay.setSpacing(6)
        title = QLabel(t("「{name}」の設定").format(name=self.library.current_shelf['name']))
        title.setObjectName("title"); lay.addWidget(title); lay.addSpacing(6)

        def action(label, desc, cb, enabled=True):
            b = QPushButton(label); b.setObjectName("act"); b.setEnabled(enabled)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(cb)
            lay.addWidget(b)
            d = QLabel(desc); d.setObjectName("desc"); d.setWordWrap(True)
            lay.addWidget(d); lay.addSpacing(8)
            return b

        action(t("✏  本棚の名前を変更"),
                t("この本棚の表示名を変更します。") if not hist else t("お気に入り・履歴棚は名前を変更できません。"),
                self._rename_current_shelf, enabled=not hist)
        action(t("🖼  サムネイルを再生成"),
                t("すべての表紙キャッシュを削除して作り直します。表紙がずれた・更新したいときに。"),
                self._regen_covers)
        action(t("📁  カバー画像の保存先を変更"),
                t("現在: {dir}").format(dir=current_covers_dir()),
                self._change_covers_dir)

        # ── 全体設定：本棚を開いたときのスクロール位置 ──
        sep = QLabel(); sep.setFixedHeight(1); sep.setStyleSheet("background:#393350;")
        lay.addWidget(sep); lay.addSpacing(8)
        sub = QLabel(t("本棚を開いたときのスクロール位置"))
        sub.setStyleSheet("color:#d8ccff;font-size:13px;font-weight:bold;")
        lay.addWidget(sub)
        pos_row = QHBoxLayout(); pos_row.setSpacing(6)
        remember_btn = ToggleBtn(t("前回の位置"), self.settings.shelf_open_pos == "remember", h=30)
        top_btn = ToggleBtn(t("一番上から"), self.settings.shelf_open_pos == "top", h=30)

        def set_pos(mode):
            self.settings.shelf_open_pos = mode; self.settings.save()
            remember_btn.set_checked(mode == "remember", silent=True)
            top_btn.set_checked(mode == "top", silent=True)
        remember_btn.set_callback(lambda _: set_pos("remember"))
        top_btn.set_callback(lambda _: set_pos("top"))
        pos_row.addWidget(remember_btn); pos_row.addWidget(top_btn); pos_row.addStretch()
        lay.addLayout(pos_row)
        d = QLabel(t("「前回の位置」は本棚ごとに前回見ていた位置で開きます。"))
        d.setObjectName("desc"); d.setWordWrap(True); lay.addWidget(d)
        # 言語・タグ管理・バックアップ・アップデート・ヘルプ等は
        # スタート画面（本棚一覧）の「⚙ 設定」に集約。

        lay.addStretch()
        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close")
        close.clicked.connect(dlg.accept)
        row.addWidget(close); lay.addLayout(row)
        dlg.exec()

    def _change_covers_dir(self):
        cur = str(current_covers_dir())
        new = QFileDialog.getExistingDirectory(self, t("カバー画像の保存先を選択"), cur)
        if not new: return
        new_dir = Path(new)
        old_dir = current_covers_dir()
        if new_dir.resolve() == old_dir.resolve():
            return
        # 既存のキャッシュを移動するか確認
        move = QMessageBox.question(
            self, t("保存先の変更"),
            t("カバー画像の保存先を変更します。\n\n新: {new_dir}\n\n").format(new_dir=new_dir)
            + t("既存のキャッシュ画像を新しい場所へ移動しますか？\n")
            + t("（「いいえ」を選ぶと次回以降の生成分のみ新しい場所に保存されます）"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        if move == QMessageBox.StandardButton.Cancel:
            return
        try:
            applied = self.settings.set_covers_dir(str(new_dir))
        except Exception as e:
            QMessageBox.warning(self, t("エラー"), t("保存先を設定できませんでした:\n{e}").format(e=e)); return
        if move == QMessageBox.StandardButton.Yes:
            moved = 0
            for pat in ("*.png", "*.jpg"):
                for f in old_dir.glob(pat):
                    try:
                        dest = applied / f.name
                        if dest.exists(): dest.unlink()
                        f.rename(dest); moved += 1
                    except Exception:
                        pass
            self.library.remap_covers(applied)
            QMessageBox.information(self, t("完了"),
                                    t("{moved} 件のカバー画像を移動しました。\n保存先:\n{applied}").format(moved=moved, applied=applied))
        else:
            QMessageBox.information(self, t("完了"), t("保存先を変更しました:\n{applied}").format(applied=applied))
        self.refresh()

    def reset_scroll(self):
        """スクロール位置を最上部に戻す（本棚を新たに開いたとき用）。"""
        self._smooth_timer.stop(); self._fling_timer.stop()
        self._scroll_target = 0.0
        self._scroll_pos_f = 0.0
        self.scroll.verticalScrollBar().setValue(0)

    def remember_scroll(self):
        """現在表示中の本棚のスクロール位置を記憶する。"""
        self._shelf_scroll[self.library.active_shelf_id] = self.scroll.verticalScrollBar().value()

    def apply_open_scroll(self):
        """設定に応じて本棚を開いたときのスクロール位置を適用する。
        「前回の位置」なら記憶した位置、「一番上から」なら 0。"""
        mode = getattr(self.settings, "shelf_open_pos", "remember")
        target = self._shelf_scroll.get(self.library.active_shelf_id, 0) if mode == "remember" else 0
        self._smooth_timer.stop(); self._fling_timer.stop()

        def _do():
            bar = self.scroll.verticalScrollBar()
            p = max(bar.minimum(), min(bar.maximum(), target))
            bar.setValue(p)
            self._scroll_target = float(p); self._scroll_pos_f = float(p)
            self._update_visible_cards()
        # レイアウト確定後に適用（スクロール範囲が未確定なケースに対応して2回）
        QTimer.singleShot(0, _do)
        QTimer.singleShot(60, _do)

    def save_scroll_pos(self) -> int: return self.scroll.verticalScrollBar().value()

    def restore_scroll_pos(self, pos: int):
        def _do():
            bar = self.scroll.verticalScrollBar()
            bar.setValue(pos); self._scroll_target = float(pos); self._scroll_pos_f = float(pos)
        QTimer.singleShot(50, _do)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()
