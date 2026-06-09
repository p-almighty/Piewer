from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QMessageBox, QInputDialog, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, Signal, QPoint, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor

from config import (Library, HISTORY_ID, HISTORY_NAME, FAVORITES_ID, FAVORITES_NAME,
                    RECENT_ID, RECENT_NAME, CONTINUE_ID, CONTINUE_NAME)
from widgets import FlatBtn
from i18n import t

# ドラッグ&ドロップで受け付ける拡張子
_DND_EXT = {".cbz", ".zip", ".cbr", ".rar", ".pdf", ".epub", ".kepub"}

ADD_ID = "__add__"   # 「新しい本棚」カードの識別子
# 並び替え不可・先頭固定の特別カード（お気に入り・履歴・追加）
PINNED_IDS = (FAVORITES_ID, HISTORY_ID, RECENT_ID, CONTINUE_ID, ADD_ID)

# レイアウト定数
CARD_W, CARD_H = 200, 140
GAP = 20
MARGIN = 30
COL_W = CARD_W + GAP
ROW_H = CARD_H + GAP


class ShelfCard(QFrame):
    """本棚カード。通常棚はドラッグで掴んで並び替えできる（手動ドラッグ）。"""
    clicked      = Signal(str)
    drag_started = Signal(object)            # card
    drag_moved   = Signal(object, QPoint)    # card, global pos
    drag_ended   = Signal(object)            # card

    def __init__(self, shelf_id: str, draggable: bool, parent=None):
        super().__init__(parent)
        self.shelf_id = shelf_id
        self._draggable = draggable
        self._press = None
        self._dragging = False
        self._moved = False
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._dragging = False
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        gp = e.globalPosition().toPoint()
        if (gp - self._press).manhattanLength() > 12:
            self._moved = True   # 少しでも動かしたらクリック扱いにしない
        if not self._draggable:
            return
        if not self._dragging and self._moved:
            self._dragging = True
            self.raise_()
            self.drag_started.emit(self)
        if self._dragging:
            self.drag_moved.emit(self, gp)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            if self._dragging:
                self.drag_ended.emit(self)
            elif not self._moved:   # 動かしていなければ（＝クリック）開く
                self.clicked.emit(self.shelf_id)
        self._press = None
        self._dragging = False
        self._moved = False


class ShelfSelectView(QWidget):
    shelf_selected = Signal(str)
    search_requested = Signal()              # 全本棚を横断検索
    quick_open_requested = Signal(str)       # ""=ファイル選択 / path=そのファイルを登録せず開く
    register_requested = Signal(str, list)   # (shelf_id, paths) 既存の本棚へ登録
    browse_requested = Signal()              # フォルダから直接開く（エクスプローラ式）
    random_requested = Signal()              # 全本棚からランダムに1冊開く

    def __init__(self, library: Library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setStyleSheet("background:#15121d;")
        self.setAcceptDrops(True)   # 本棚へD&D=登録 / 何もない所へD&D=登録せず開く
        self._cards: list[ShelfCard] = []
        self._anims: dict = {}
        self._drag_card = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet("background:#1f1a29;border-bottom:1px solid #2b2539;")
        hl = QHBoxLayout(header); hl.setContentsMargins(20, 0, 20, 0)
        self._title_lbl = QLabel(t("本棚を選択してください"))
        self._title_lbl.setStyleSheet("color:#ddd;font-size:18px;font-weight:bold;")
        self._hint = QLabel(t("（本棚はドラッグで並び替えできます）"))
        self._hint.setStyleSheet("color:#777;font-size:12px;margin-left:12px;")
        hl.addWidget(self._title_lbl); hl.addWidget(self._hint)
        hl.addSpacing(14)
        self._search_btn = FlatBtn(t("🔍 全本棚を検索"), h=34, font_size=13)
        self._search_btn.set_callback(self.search_requested.emit)
        hl.addWidget(self._search_btn)
        hl.addSpacing(6)
        self._quick_btn = FlatBtn(t("📂 登録せず開く"), h=34, font_size=13)
        self._quick_btn.set_callback(lambda: self.quick_open_requested.emit(""))
        hl.addWidget(self._quick_btn)
        hl.addSpacing(6)
        self._browse_btn = FlatBtn(t("📁 フォルダから開く"), h=34, font_size=13)
        self._browse_btn.set_callback(self.browse_requested.emit)
        hl.addWidget(self._browse_btn)
        hl.addSpacing(6)
        self._random_btn = FlatBtn(t("🎲 ランダム"), h=34, font_size=13)
        self._random_btn.setToolTip(t("全本棚からランダムに1冊開く"))
        self._random_btn.set_callback(self.random_requested.emit)
        hl.addWidget(self._random_btn)
        hl.addStretch()
        self._settings_btn = FlatBtn(t("⚙ 設定"), h=34, font_size=14)
        self._settings_btn.set_callback(self._open_settings)
        hl.addWidget(self._settings_btn)
        root.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:#15121d;}")
        self._container = QWidget()
        self._container.setStyleSheet("background:#15121d;")
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

    def _open_settings(self):
        win = self.window()
        if hasattr(win, "open_global_settings"):
            win.open_global_settings(self)

    def retranslate(self):
        self._title_lbl.setText(t("本棚を選択してください"))
        self._hint.setText(t("（本棚はドラッグで並び替えできます）"))
        self._search_btn.setText(t("🔍 全本棚を検索"))
        self._quick_btn.setText(t("📂 登録せず開く"))
        self._browse_btn.setText(t("📁 フォルダから開く"))
        self._random_btn.setText(t("🎲 ランダム"))
        self._settings_btn.setText(t("⚙ 設定"))
        self.refresh()

    # ── ドラッグ&ドロップ（本棚へ=登録 / 何もない所へ=登録せず開く）──────

    @staticmethod
    def _dnd_paths(md) -> list[str]:
        out = []
        if not md.hasUrls():
            return out
        for u in md.urls():
            p = u.toLocalFile()
            if not p:
                continue
            path = Path(p)
            if path.is_dir() or path.suffix.lower() in _DND_EXT:
                out.append(p)
        return out

    def _card_at(self, view_pos: QPoint):
        """ビュー座標 view_pos の下にある本棚カードを返す（なければ None）。"""
        cont_pos = self._container.mapFrom(self, view_pos)
        for card in self._cards:
            if card.geometry().contains(cont_pos):
                return card
        return None

    def _shelf_name(self, sid: str) -> str:
        return next((s["name"] for s in self.library.shelves if s["id"] == sid), "")

    def _drag_hint_label(self) -> QLabel:
        if not hasattr(self, "_hint_lbl"):
            self._hint_lbl = QLabel(self)
            self._hint_lbl.hide()
        return self._hint_lbl

    def _show_drag_hint(self, text: str, pos: QPoint, ok: bool):
        lbl = self._drag_hint_label()
        bg = "#a06cff" if ok else "#c0392b"
        lbl.setStyleSheet(f"background:{bg};color:white;border-radius:8px;"
                          "padding:4px 10px;font-size:12px;font-weight:bold;")
        lbl.setText(text); lbl.adjustSize()
        x = min(pos.x() + 18, self.width() - lbl.width() - 4)
        y = min(pos.y() + 18, self.height() - lbl.height() - 4)
        lbl.move(max(0, x), max(0, y)); lbl.show(); lbl.raise_()

    def _hide_drag_hint(self):
        if hasattr(self, "_hint_lbl"):
            self._hint_lbl.hide()

    def _drag_target(self, event):
        """ドロップ先を判定して (種別, paths, card) を返す。
        種別: 'shelf'（通常棚へ登録）/ 'reject'（お気に入り・履歴）/ 'open'（登録せず開く）/ None。"""
        paths = self._dnd_paths(event.mimeData())
        if not paths:
            return None, [], None
        card = self._card_at(event.position().toPoint())
        sid = card.shelf_id if card is not None else None
        if sid in (FAVORITES_ID, HISTORY_ID):
            return "reject", paths, card
        if card is not None and sid not in PINNED_IDS:
            return "shelf", paths, card
        return "open", paths, card

    def dragEnterEvent(self, event):
        self.dragMoveEvent(event)

    def dragMoveEvent(self, event):
        kind, paths, card = self._drag_target(event)
        pos = event.position().toPoint()
        if kind is None:
            self._hide_drag_hint(); event.ignore(); return
        if kind == "reject":
            self._show_drag_hint(t("ここには登録できません"), pos, ok=False)
            event.ignore()   # 禁止カーソルになる（ドロップ不可）
        elif kind == "shelf":
            self._show_drag_hint(
                t("「{name}」へ登録").format(name=self._shelf_name(card.shelf_id)), pos, ok=True)
            event.setDropAction(Qt.DropAction.CopyAction); event.accept()
        else:
            self._show_drag_hint(t("登録せずに開く"), pos, ok=True)
            event.setDropAction(Qt.DropAction.CopyAction); event.accept()

    def dragLeaveEvent(self, event):
        self._hide_drag_hint()

    def dropEvent(self, event):
        kind, paths, card = self._drag_target(event)
        self._hide_drag_hint()
        if kind in (None, "reject") or not paths:
            event.ignore(); return
        event.acceptProposedAction()
        if kind == "shelf":
            self.register_requested.emit(card.shelf_id, paths)   # 通常の本棚へ登録
        else:
            self.quick_open_requested.emit(paths[0])             # 登録せずに開く

    # ── レイアウト計算 ──────────────────────────────────────

    def _cols(self) -> int:
        w = self._container.width() or self.width()
        return max(1, (w - 2 * MARGIN + GAP) // COL_W)

    def _slot_pos(self, index: int, cols: int) -> QPoint:
        row, col = divmod(index, cols)
        return QPoint(MARGIN + col * COL_W, MARGIN + row * ROW_H)

    def _relayout(self, animated: bool, skip=None):
        cols = self._cols()
        for i, card in enumerate(self._cards):
            if card is skip:
                continue
            target = self._slot_pos(i, cols)
            if animated:
                self._animate(card, target)
            else:
                card.move(target)
        rows = (len(self._cards) + cols - 1) // cols
        self._container.setMinimumHeight(MARGIN * 2 + rows * ROW_H)

    def _animate(self, card, target: QPoint):
        if card.pos() == target:
            return
        old = self._anims.get(card)
        if old:
            old.stop()
        a = QPropertyAnimation(card, b"pos", self)
        a.setDuration(180)
        a.setStartValue(card.pos())
        a.setEndValue(target)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.start()
        self._anims[card] = a

    # ── カード生成 ──────────────────────────────────────────

    def refresh(self):
        for c in self._cards:
            c.setParent(None); c.deleteLater()
        self._cards = []; self._anims = {}; self._drag_card = None

        self._cards.append(self._make_favorites_card())
        self._cards.append(self._make_history_card())
        self._cards.append(self._make_continue_card())
        self._cards.append(self._make_recent_card())
        for shelf in self.library.shelves:
            self._cards.append(self._make_shelf_card(shelf))
        self._cards.append(self._make_add_card())

        for c in self._cards:
            self._add_shadow(c)
            c.show()
        self._relayout(animated=False)

    @staticmethod
    def _add_shadow(card):
        """カードにふんわりした影をつけて立体感（ポップさ）を出す。"""
        eff = QGraphicsDropShadowEffect(card)
        eff.setBlurRadius(26); eff.setOffset(0, 5)
        eff.setColor(QColor(0, 0, 0, 120))
        card.setGraphicsEffect(eff)

    def _make_favorites_card(self) -> ShelfCard:
        w = ShelfCard(FAVORITES_ID, draggable=False, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#3a3320;border-radius:14px;border:2px solid #8a7320;} "
                        "ShelfCard:hover{border-color:#ffc107;background:#463d22;}")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 14, 14, 10); lay.setSpacing(6)
        icon = QLabel("★"); icon.setStyleSheet("font-size:28px;color:#ffc107;background:transparent;")
        name_lbl = QLabel(t(FAVORITES_NAME))
        name_lbl.setStyleSheet("color:#ffe08a;font-size:16px;font-weight:bold;background:transparent;")
        name_lbl.setWordWrap(True)
        count_lbl = QLabel(t("{n} 冊").format(n=len(self.library.favorite_books())))
        count_lbl.setStyleSheet("color:#cdb066;font-size:12px;background:transparent;")
        lay.addWidget(icon); lay.addWidget(name_lbl); lay.addWidget(count_lbl); lay.addStretch()
        w.clicked.connect(self._on_card_clicked)
        return w

    def _make_history_card(self) -> ShelfCard:
        w = ShelfCard(HISTORY_ID, draggable=False, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#1e3330;border-radius:14px;border:2px solid #2f6f63;} "
                        "ShelfCard:hover{border-color:#3fd0c0;background:#244038;}")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 14, 14, 10); lay.setSpacing(6)
        icon = QLabel("🕒"); icon.setStyleSheet("font-size:28px;background:transparent;")
        name_lbl = QLabel(t(HISTORY_NAME))
        name_lbl.setStyleSheet("color:#b8f0e6;font-size:16px;font-weight:bold;background:transparent;")
        name_lbl.setWordWrap(True)
        count_lbl = QLabel(t("{n} 冊").format(n=len(self.library.history_books())))
        count_lbl.setStyleSheet("color:#6fb5a8;font-size:12px;background:transparent;")
        lay.addWidget(icon); lay.addWidget(name_lbl); lay.addWidget(count_lbl); lay.addStretch()
        w.clicked.connect(self._on_card_clicked)
        return w

    def _make_continue_card(self) -> ShelfCard:
        w = ShelfCard(CONTINUE_ID, draggable=False, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#2a2433;border-radius:14px;border:2px solid #5b4a7a;} "
                        "ShelfCard:hover{border-color:#a06cff;background:#322a45;}")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 14, 14, 10); lay.setSpacing(6)
        icon = QLabel("▶"); icon.setStyleSheet("font-size:26px;color:#b488ff;background:transparent;")
        name_lbl = QLabel(t(CONTINUE_NAME))
        name_lbl.setStyleSheet("color:#d8ccff;font-size:16px;font-weight:bold;background:transparent;")
        name_lbl.setWordWrap(True)
        count_lbl = QLabel(t("{n} 冊").format(n=len(self.library.continue_books())))
        count_lbl.setStyleSheet("color:#9a8fc0;font-size:12px;background:transparent;")
        lay.addWidget(icon); lay.addWidget(name_lbl); lay.addWidget(count_lbl); lay.addStretch()
        w.clicked.connect(self._on_card_clicked)
        return w

    def _make_recent_card(self) -> ShelfCard:
        w = ShelfCard(RECENT_ID, draggable=False, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#1f2c33;border-radius:14px;border:2px solid #356073;} "
                        "ShelfCard:hover{border-color:#4fb0d0;background:#243640;}")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 14, 14, 10); lay.setSpacing(6)
        icon = QLabel("🆕"); icon.setStyleSheet("font-size:26px;background:transparent;")
        name_lbl = QLabel(t(RECENT_NAME))
        name_lbl.setStyleSheet("color:#bfe6f0;font-size:16px;font-weight:bold;background:transparent;")
        name_lbl.setWordWrap(True)
        count_lbl = QLabel(t("{n} 冊").format(n=len(self.library.recent_books())))
        count_lbl.setStyleSheet("color:#73b0c0;font-size:12px;background:transparent;")
        lay.addWidget(icon); lay.addWidget(name_lbl); lay.addWidget(count_lbl); lay.addStretch()
        w.clicked.connect(self._on_card_clicked)
        return w

    def _make_add_card(self) -> ShelfCard:
        w = ShelfCard(ADD_ID, draggable=False, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#241f31;border-radius:14px;border:2px dashed #393350;} ShelfCard:hover{border-color:#a06cff;}")
        lay = QVBoxLayout(w); lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus = QLabel("+"); plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet("color:#463d63;font-size:36px;background:transparent;")
        lbl = QLabel(t("新しい本棚")); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color:#463d63;font-size:13px;background:transparent;")
        lay.addWidget(plus); lay.addWidget(lbl)
        w.clicked.connect(self._on_card_clicked)
        return w

    def _make_shelf_card(self, shelf) -> ShelfCard:
        w = ShelfCard(shelf["id"], draggable=True, parent=self._container)
        w.setStyleSheet("ShelfCard{background:#241f31;border-radius:14px;border:2px solid #2b2539;} ShelfCard:hover{border-color:#a06cff;background:#2f2840;}")
        lay = QVBoxLayout(w); lay.setContentsMargins(14, 14, 14, 10); lay.setSpacing(6)
        name_lbl = QLabel(shelf["name"])
        name_lbl.setStyleSheet("color:#ddd;font-size:16px;font-weight:bold;background:transparent;")
        name_lbl.setWordWrap(True)
        count_lbl = QLabel(t("{n} 冊").format(n=len(shelf['books'])))
        count_lbl.setStyleSheet("color:#888;font-size:12px;background:transparent;")
        lay.addWidget(name_lbl); lay.addWidget(count_lbl); lay.addStretch()

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        rename_b = FlatBtn(t("名前変更"), h=24); rename_b.set_callback(lambda s=shelf["id"]: self._rename(s))
        if len(self.library.shelves) > 1:
            del_b = FlatBtn(t("削除"), h=24); del_b.set_callback(lambda s=shelf["id"]: self._delete(s))
            btn_row.addWidget(rename_b); btn_row.addWidget(del_b)
        else:
            btn_row.addWidget(rename_b)
        lay.addLayout(btn_row)

        w.clicked.connect(self._on_card_clicked)
        w.drag_started.connect(self._on_drag_started)
        w.drag_moved.connect(self._on_drag_moved)
        w.drag_ended.connect(self._on_drag_ended)
        return w

    # ── クリック ────────────────────────────────────────────

    def _on_card_clicked(self, sid: str):
        if sid == ADD_ID:
            self._add_shelf()
        else:
            self.shelf_selected.emit(sid)

    # ── ドラッグ並び替え ────────────────────────────────────

    def _insertion_index(self, gp: QPoint) -> int:
        p = self._container.mapFromGlobal(gp)
        cols = self._cols()
        col = min(max(round((p.x() - MARGIN) / COL_W), 0), cols - 1)
        row = max(0, round((p.y() - MARGIN) / ROW_H))
        idx = row * cols + col
        # 先頭固定（お気に入り0・履歴1）とaddカード(末尾)の間にだけ入れられるよう制限
        return min(max(idx, 2), len(self._cards) - 2)

    def _on_drag_started(self, card):
        self._drag_card = card
        card.raise_()

    def _on_drag_moved(self, card, gp: QPoint):
        if self._drag_card is None:
            return
        # ドラッグ中のカードはカーソルに追従（中央）
        p = self._container.mapFromGlobal(gp)
        card.move(p.x() - CARD_W // 2, p.y() - CARD_H // 2)
        # 挿入位置を計算し、必要なら並び替えて他カードをスライド
        idx = self._insertion_index(gp)
        cur = self._cards.index(card)
        if idx != cur:
            self._cards.pop(cur)
            self._cards.insert(idx, card)
            self._relayout(animated=True, skip=card)

    def _on_drag_ended(self, card):
        if self._drag_card is None:
            return
        self._drag_card = None
        ids = [c.shelf_id for c in self._cards if c.shelf_id not in PINNED_IDS]
        self.library.set_shelf_order(ids)
        self._relayout(animated=True)   # 掴んでいたカードをスロットへスナップ

    # ── 棚の追加・名前変更・削除 ────────────────────────────

    def _add_shelf(self):
        name, ok = QInputDialog.getText(self, t("新しい本棚"), t("本棚の名前:"))
        if ok and name.strip():
            self.library.add_shelf(name.strip()); self.refresh()

    def _rename(self, sid: str):
        shelf = next((s for s in self.library.shelves if s["id"] == sid), None)
        if not shelf: return
        name, ok = QInputDialog.getText(self, t("名前を変更"), t("新しい名前:"), text=shelf["name"])
        if ok and name.strip():
            self.library.rename_shelf(sid, name.strip()); self.refresh()

    def _delete(self, sid: str):
        shelf = next((s for s in self.library.shelves if s["id"] == sid), None)
        if not shelf: return
        n = len(shelf["books"])
        if QMessageBox.question(self, t("削除"),
                                t("「{name}」を削除しますか？\n（{n} 冊の情報も削除されます）").format(name=shelf['name'], n=n),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.library.delete_shelf(sid); self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, lambda: self._relayout(animated=False))
