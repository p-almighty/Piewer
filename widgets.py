from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QHBoxLayout, QPushButton,
                               QDialog, QVBoxLayout, QTextBrowser, QGridLayout,
                               QScrollArea, QLineEdit, QCompleter, QLayout,
                               QInputDialog, QMessageBox, QCheckBox,
                               QTreeWidget, QTreeWidgetItem)
from PySide6.QtCore import (Qt, Signal, QPoint, QRect, QSize, QTimer,
                            QPropertyAnimation, QEasingCurve)
from PySide6.QtGui import (QPixmap, QPainter, QColor, QFont, QKeySequence, QPainterPath,
                           QStandardItemModel, QStandardItem)
# 注: 配色・角丸の各値は theme.py に集約。以下のインラインQSSもその値に揃えている。

from config import APP_NAME, APP_VERSION, SHORTCUT_LABELS
import i18n
from i18n import t
import theme
import unicodedata


def fold_text(s: str) -> str:
    """検索照合用に正規化：全角/半角・カタカナ/ひらがな・大文字小文字の違いを吸収。

    NFKCで全半角を統一（半角カナ→全角カナ・全角英数→半角等）→ casefold で大小無視 →
    カタカナをひらがなへ畳む。これで「ふじさき」と「フジサキ」「ﾌｼﾞｻｷ」が一致する。
    """
    s = unicodedata.normalize("NFKC", s).casefold()
    out = []
    for ch in s:
        o = ord(ch)
        out.append(chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else ch)  # カタカナ→ひらがな
    return "".join(out)


def make_fold_completer(items, parent=None):
    """ひらがな/カタカナ・全角/半角・大小を区別しない部分一致サジェストを返す。

    表示・確定は元のラベルのまま（照合だけ fold_text したキーで行う）。
    """
    comp = _FoldCompleter(parent)
    model = QStandardItemModel(comp)        # completer を親にして寿命を束ねる（GC防止）
    for s in sorted(set(items)):
        it = QStandardItem(s)                                   # 表示・確定は元ラベル
        it.setData(fold_text(s), Qt.ItemDataRole.UserRole)     # 照合キー（畳んだ文字）
        model.appendRow(it)
    comp.setModel(model)
    comp._model = model                     # 念のため Python 参照も保持
    comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    comp.setFilterMode(Qt.MatchFlag.MatchContains)
    comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    comp.setCompletionRole(Qt.ItemDataRole.UserRole)           # 畳んだキーで照合
    comp.setMaxVisibleItems(8)                                 # 候補ポップアップを高くしすぎない
    popup = comp.popup()                                       # コンパクトな見た目に整える
    popup.setStyleSheet(
        "QListView{background:#262032;color:#ddd;border:1px solid #463d63;"
        "border-radius:8px;font-size:12px;outline:none;padding:2px;}"
        "QListView::item{padding:2px 8px;min-height:20px;}"
        "QListView::item:selected{background:#a06cff;color:white;}"
        "QScrollBar:vertical{background:#18151f;width:12px;}"
        "QScrollBar::handle:vertical{background:#393350;border-radius:6px;min-height:30px;}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
    return comp


class _FoldCompleter(QCompleter):
    def splitPath(self, path):
        return [fold_text(path)]                # 入力も畳んでから照合

    def pathFromIndex(self, index):
        # 確定時は表示名（元ラベル）を入力欄へ入れる（畳んだキーは入れない）
        return index.data(Qt.ItemDataRole.DisplayRole)


MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                 Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_unknown}


class ShortcutsDialog(QDialog):
    """リーダー操作のキー割り当てを確認・変更するダイアログ。"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._capturing = None          # 入力待ち中のアクション名
        self._key_labels: dict[str, QLabel] = {}
        self.setWindowTitle(t("ショートカットの設定"))
        self.setMinimumWidth(540)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:5px 14px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#primary { background:#a06cff; color:white; border:none; padding:7px 26px; }
            QPushButton#primary:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)

        head = QLabel(t("各操作の「変更」を押し、割り当てたいキーを押してください。")
                      + t("（Esc で取消・1操作1キー）"))
        head.setStyleSheet("color:#c9b6ff;font-size:12px;background:transparent;")
        head.setWordWrap(True)
        lay.addWidget(head)

        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for row, (action, label) in enumerate(SHORTCUT_LABELS.items()):
            name_lbl = QLabel(t(label))
            keys_lbl = QLabel(self._keys_text(action))
            keys_lbl.setStyleSheet("color:#bfa6ff;font-size:13px;font-weight:bold;"
                                   "background:#1f1a29;border:1px solid #393350;"
                                   "border-radius:10px;padding:4px 10px;")
            keys_lbl.setMinimumWidth(150)
            keys_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._key_labels[action] = keys_lbl
            change_btn = QPushButton(t("変更"))
            change_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            change_btn.clicked.connect(lambda _=False, a=action: self._start_capture(a))
            grid.addWidget(name_lbl, row, 0)
            grid.addWidget(keys_lbl, row, 1)
            grid.addWidget(change_btn, row, 2)
        lay.addLayout(grid)

        row = QHBoxLayout()
        reset = QPushButton(t("すべて既定に戻す")); reset.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        reset.clicked.connect(self._reset_all)
        row.addWidget(reset); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("primary")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _keys_text(self, action: str) -> str:
        keys = self.settings.shortcuts.get(action, [])
        return " / ".join(keys) if keys else t("（なし）")

    def _refresh(self):
        for action, lbl in self._key_labels.items():
            lbl.setText(self._keys_text(action))

    def _start_capture(self, action: str):
        self._capturing = action
        self._key_labels[action].setText(t("キーを押してください…"))
        self._key_labels[action].setStyleSheet(
            "color:#222;font-size:13px;font-weight:bold;background:#ffc107;"
            "border-radius:10px;padding:4px 10px;")
        self.setFocus(); self.grabKeyboard()

    def _stop_capture(self):
        action = self._capturing
        self._capturing = None
        try: self.releaseKeyboard()
        except Exception: pass
        if action:
            self._key_labels[action].setStyleSheet(
                "color:#bfa6ff;font-size:13px;font-weight:bold;background:#1f1a29;"
                "border:1px solid #393350;border-radius:10px;padding:4px 10px;")
        self._refresh()

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event); return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._stop_capture(); return
        if key in MODIFIER_KEYS:
            return  # 修飾キー単体は無視（次の押下を待つ）
        name = QKeySequence(key).toString()
        if not name:
            return
        action = self._capturing
        # 同じキーが他アクションに割り当て済みなら外して重複を防ぐ
        for other, keys in self.settings.shortcuts.items():
            if other != action and name in keys:
                self.settings.shortcuts[other] = [k for k in keys if k != name]
        self.settings.set_shortcut(action, [name])
        self._stop_capture()

    def _reset_all(self):
        self.settings.reset_shortcuts()
        self._refresh()

    def closeEvent(self, event):
        try: self.releaseKeyboard()
        except Exception: pass
        super().closeEvent(event)


def show_shortcuts_dialog(settings, parent=None):
    if settings is None:
        return
    ShortcutsDialog(settings, parent).exec()


def show_help_dialog(parent=None, settings=None):
    """操作一覧＋バージョン情報を表示するヘルプダイアログ。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("{name} のヘルプ").format(name=APP_NAME))
    dlg.setMinimumSize(520, 560)
    dlg.setStyleSheet("""
        QDialog { background:#262032; }
        QPushButton { background:#a06cff; color:white; border:none;
                      border-radius:10px; padding:7px 26px; font-size:13px; min-width:80px; }
        QPushButton:hover { background:#b488ff; }
        QTextBrowser { background:#1f1a29; color:#ddd; border:1px solid #393350;
                       border-radius:12px; font-size:13px; padding:10px; }
    """)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(12)

    body = QTextBrowser(); body.setOpenExternalLinks(True)
    body.setHtml(_help_html_en() if i18n.get_lang() == "en" else _help_html_ja())
    lay.addWidget(body)

    row = QHBoxLayout()
    if settings is not None:
        sc_btn = QPushButton(t("⌨ ショートカット設定"))
        sc_btn.setStyleSheet("background:#322b45;color:#ddd;border:1px solid #463d63;"
                             "border-radius:10px;padding:7px 18px;font-size:13px;")
        sc_btn.clicked.connect(lambda: show_shortcuts_dialog(settings, dlg))
        row.addWidget(sc_btn)
    row.addStretch()
    ok = QPushButton(t("閉じる")); ok.clicked.connect(dlg.accept)
    row.addWidget(ok); lay.addLayout(row)
    dlg.exec()


def _help_html_ja() -> str:
    return f"""
    <h2 style="color:#d8ccff;margin:0;">{APP_NAME} <span style="color:#888;font-size:14px;">v{APP_VERSION}</span></h2>
    <p style="color:#aaa;">Windows向けローカル漫画ビュワー</p>
    <hr style="border-color:#393350;">
    <h3 style="color:#b39dff;">📖 ページ操作</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">画面 左／右クリック</td><td>前のページ／次のページ</td></tr>
      <tr><td style="color:#bfa6ff;">ドラッグ（スワイプ）</td><td>ページめくり</td></tr>
      <tr><td style="color:#bfa6ff;">← → ↑ ↓ / A D W S</td><td>ページ移動</td></tr>
      <tr><td style="color:#bfa6ff;">Home / End</td><td>最初／最後のページ</td></tr>
      <tr><td style="color:#bfa6ff;">マウスホイール</td><td>ズーム（最大8倍・カーソル中心）</td></tr>
      <tr><td style="color:#bfa6ff;">ズーム中ドラッグ</td><td>表示位置の移動（パン）</td></tr>
    </table>
    <h3 style="color:#b39dff;">🛠 メニュー・画面</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">画面中央クリック／右クリック</td><td>メニュー(HUD)の表示・非表示</td></tr>
      <tr><td style="color:#bfa6ff;">「← 本棚」／ Esc</td><td>本棚に戻る</td></tr>
      <tr><td style="color:#bfa6ff;">F11</td><td>全画面の切り替え</td></tr>
      <tr><td style="color:#bfa6ff;">下部サムネイル</td><td>クリックでそのページへジャンプ</td></tr>
      <tr><td style="color:#bfa6ff;">🔖 しおり</td><td>現在ページに目印／「しおり ▾」で一覧・ジャンプ</td></tr>
      <tr><td style="color:#bfa6ff;">[ ／ ]</td><td>前／次のしおりへジャンプ</td></tr>
      <tr><td style="color:#bfa6ff;">「幅」ボタン</td><td>幅に合わせる（ホイールで縦スクロール）</td></tr>
      <tr><td style="color:#bfa6ff;">「縦読み」ボタン</td><td>縦スクロールの連続表示（Webtoon向け）</td></tr>
      <tr><td style="color:#bfa6ff;">マウス 戻る／進むボタン</td><td>本棚へ戻る／直前の本を再開</td></tr>
      <tr><td style="color:#bfa6ff;">⌨ ショートカット設定</td><td>下のボタンからキー割り当てを変更</td></tr>
    </table>
    <p style="color:#888;font-size:12px;">※ 右綴じ/見開き/幅/縦読みなどの表示設定は本ごとに記憶されます。</p>
    <h3 style="color:#b39dff;">📚 本棚</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">「＋ ファイル」</td><td>漫画を追加（ZIP/CBZ/RAR/CBR/PDF）</td></tr>
      <tr><td style="color:#bfa6ff;">本棚をドラッグ</td><td>並び順を入れ替え</td></tr>
      <tr><td style="color:#bfa6ff;">本を右クリック</td><td>お気に入り・タグ編集・別の本棚へ移動・削除</td></tr>
      <tr><td style="color:#bfa6ff;">🏷 絞り込み</td><td>お気に入り／タグで本棚を絞り込み</td></tr>
      <tr><td style="color:#bfa6ff;">選択削除モード＋Shiftクリック</td><td>範囲選択して一括削除・一括移動</td></tr>
      <tr><td style="color:#bfa6ff;">🕒 最近読んだ本</td><td>最近開いた本の履歴（最大100冊）</td></tr>
    </table>
    <hr style="border-color:#393350;">
    <p style="color:#888;font-size:12px;">
      制作者: P ／ X: <a href="https://x.com/p_almighty" style="color:#a06cff;">@p_almighty</a><br>
      © 2026 P. All rights reserved.
    </p>
    """


def _help_html_en() -> str:
    return f"""
    <h2 style="color:#d8ccff;margin:0;">{APP_NAME} <span style="color:#888;font-size:14px;">v{APP_VERSION}</span></h2>
    <p style="color:#aaa;">Local manga viewer for Windows</p>
    <hr style="border-color:#393350;">
    <h3 style="color:#b39dff;">📖 Page controls</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">Left / right click</td><td>Previous / next page</td></tr>
      <tr><td style="color:#bfa6ff;">Drag (swipe)</td><td>Turn page</td></tr>
      <tr><td style="color:#bfa6ff;">← → ↑ ↓ / A D W S</td><td>Move pages</td></tr>
      <tr><td style="color:#bfa6ff;">Home / End</td><td>First / last page</td></tr>
      <tr><td style="color:#bfa6ff;">Mouse wheel</td><td>Zoom (up to 8×, centered on cursor)</td></tr>
      <tr><td style="color:#bfa6ff;">Drag while zoomed</td><td>Pan</td></tr>
    </table>
    <h3 style="color:#b39dff;">🛠 Menu &amp; screen</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">Center / right click</td><td>Show / hide menu (HUD)</td></tr>
      <tr><td style="color:#bfa6ff;">“← Shelves” / Esc</td><td>Back to shelves</td></tr>
      <tr><td style="color:#bfa6ff;">F11</td><td>Toggle fullscreen</td></tr>
      <tr><td style="color:#bfa6ff;">Bottom thumbnails</td><td>Click to jump to a page</td></tr>
      <tr><td style="color:#bfa6ff;">🔖 Bookmark</td><td>Mark current page / “Bookmarks ▾” to list &amp; jump</td></tr>
      <tr><td style="color:#bfa6ff;">[ / ]</td><td>Jump to previous / next bookmark</td></tr>
      <tr><td style="color:#bfa6ff;">“Width” button</td><td>Fit width (wheel scrolls vertically)</td></tr>
      <tr><td style="color:#bfa6ff;">“Vertical” button</td><td>Continuous vertical scroll (Webtoon)</td></tr>
      <tr><td style="color:#bfa6ff;">Mouse back / forward</td><td>Back to shelves / resume last book</td></tr>
      <tr><td style="color:#bfa6ff;">⌨ Shortcut settings</td><td>Change key bindings from the button below</td></tr>
    </table>
    <p style="color:#888;font-size:12px;">※ Display settings (R→L / spread / width / vertical) are remembered per book.</p>
    <h3 style="color:#b39dff;">📚 Shelves</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">“+ File”</td><td>Add manga (ZIP/CBZ/RAR/CBR/PDF)</td></tr>
      <tr><td style="color:#bfa6ff;">Drag a shelf</td><td>Reorder</td></tr>
      <tr><td style="color:#bfa6ff;">Right-click a book</td><td>Favorite / edit tags / move to another shelf / remove</td></tr>
      <tr><td style="color:#bfa6ff;">🏷 Filter</td><td>Filter by favorites / tags</td></tr>
      <tr><td style="color:#bfa6ff;">Select &amp; Delete + Shift-click</td><td>Range-select to delete / move in bulk</td></tr>
      <tr><td style="color:#bfa6ff;">🕒 Recently Read</td><td>History of recently opened books (up to 100)</td></tr>
    </table>
    <hr style="border-color:#393350;">
    <p style="color:#888;font-size:12px;">
      Created by P / X: <a href="https://x.com/p_almighty" style="color:#a06cff;">@p_almighty</a><br>
      © 2026 P. All rights reserved.
    </p>
    """


def show_global_settings(win, parent=None):
    """スタート画面から開くアプリ全体の設定（言語・開発を支援・データ・ヘルプ等）。"""
    s = win.settings
    dlg = QDialog(parent or win)
    dlg.setWindowTitle(t("設定"))
    dlg.setMinimumWidth(460)
    dlg.resize(480, 640)            # 画面に収まる高さにし、中身はスクロール
    dlg.setStyleSheet("""
        QDialog { background:#262032; }
        QLabel { color:#ddd; font-size:13px; }
        QLabel#sub { color:#d8ccff; font-size:13px; font-weight:bold; }
        QLabel#desc { color:#888; font-size:11px; }
        QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                      border-radius:10px; padding:9px 14px; font-size:13px; text-align:left; }
        QPushButton:hover:enabled { background:#423a5a; border-color:#a06cff; }
        QPushButton#close { background:#a06cff; color:white; border:none;
                            text-align:center; padding:7px 24px; }
        QPushButton#close:hover { background:#b488ff; }
    """)
    # 項目が多いのでスクロール可能にする（閉じるボタンは下部固定）
    outer = QVBoxLayout(dlg); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
    content = QWidget(); content.setStyleSheet("background:transparent;")
    lay = QVBoxLayout(content); lay.setContentsMargins(20, 18, 20, 10); lay.setSpacing(6)
    _scroll = QScrollArea(); _scroll.setWidgetResizable(True); _scroll.setWidget(content)
    _scroll.setFrameShape(QFrame.Shape.NoFrame)
    _scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} "
                          "QScrollBar:vertical{background:#1f1a29;width:12px;} "
                          "QScrollBar::handle:vertical{background:#393350;border-radius:6px;min-height:40px;} "
                          "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
    outer.addWidget(_scroll, 1)

    def sub(text):
        sep = QLabel(); sep.setFixedHeight(1); sep.setStyleSheet("background:#393350;")
        lay.addWidget(sep); lay.addSpacing(6)
        lb = QLabel(text); lb.setObjectName("sub"); lay.addWidget(lb)

    def desc(text):
        d = QLabel(text); d.setObjectName("desc"); d.setWordWrap(True); lay.addWidget(d); lay.addSpacing(6)

    def action(label, description, cb):
        b = QPushButton(label); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(cb); lay.addWidget(b)
        desc(description)

    # ── 開発を支援 ──
    sub(t("💗  開発を支援"))
    desc(t("Piewer は完全無料・オープンソースです。気に入ったら開発の支援（寄付）をご検討ください。"))
    sup_row = QHBoxLayout(); sup_row.setSpacing(6)
    sup_btn = QPushButton(t("💗  開発を支援する (Ko-fi)"))
    sup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    sup_btn.clicked.connect(win.open_support)
    sup_row.addWidget(sup_btn); sup_row.addStretch()
    lay.addLayout(sup_row); lay.addSpacing(8)

    # ── 言語 / Language ──
    sub(t("言語 / Language"))
    lang_row = QHBoxLayout(); lang_row.setSpacing(6)
    ja_btn = ToggleBtn(t("日本語"), s.lang == "ja", h=30)
    en_btn = ToggleBtn(t("English"), s.lang == "en", h=30)

    def set_lang(code):
        s.lang = code; s.save(); i18n.set_lang(code)
        ja_btn.set_checked(code == "ja", silent=True)
        en_btn.set_checked(code == "en", silent=True)
        if hasattr(win, "retranslate_ui"):
            win.retranslate_ui()
    ja_btn.set_callback(lambda _: set_lang("ja"))
    en_btn.set_callback(lambda _: set_lang("en"))
    lang_row.addWidget(ja_btn); lang_row.addWidget(en_btn); lang_row.addStretch()
    lay.addLayout(lang_row)
    desc(t("言語はすぐに切り替わります。"))

    # ── 外観（テーマ・アクセント色）──
    sub(t("🎨  外観"))
    th_row = QHBoxLayout(); th_row.setSpacing(6)
    th_lbl = QLabel(t("テーマ:")); th_lbl.setStyleSheet("color:#888;background:transparent;")
    th_row.addWidget(th_lbl)
    dark_btn = ToggleBtn(t("ダーク"), getattr(s, "theme", "dark") == "dark", h=30)
    light_btn = ToggleBtn(t("ライト"), getattr(s, "theme", "dark") == "light", h=30)

    def set_theme_pref(name):
        s.theme = name; s.save()
        dark_btn.set_checked(name == "dark", silent=True)
        light_btn.set_checked(name == "light", silent=True)
    dark_btn.set_callback(lambda _: set_theme_pref("dark"))
    light_btn.set_callback(lambda _: set_theme_pref("light"))
    th_row.addWidget(dark_btn); th_row.addWidget(light_btn); th_row.addStretch()
    lay.addLayout(th_row)

    ac_row = QHBoxLayout(); ac_row.setSpacing(8)
    ac_btns = {}

    def refresh_ac():
        cur = getattr(s, "accent", "violet")
        for nm, b in ac_btns.items():
            sel = (nm == cur)
            col = theme.ACCENT_PRESETS[nm][0]
            qss = (f"QPushButton{{background:{col};border-radius:14px;"
                   f"border:3px solid {'#fff' if sel else 'transparent'};}}")
            # 色見本はテーマ置換を通さない（violet見本が選択色に化けるのを防ぐ）
            raw = getattr(b, "setStyleSheetRaw", None)
            (raw or b.setStyleSheet)(qss)

    def pick_accent(nm):
        s.accent = nm; s.save(); refresh_ac()

    for nm in theme.ACCENT_PRESETS:
        b = QPushButton(); b.setFixedSize(28, 28); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(t(theme.ACCENT_LABELS.get(nm, nm)))
        b.clicked.connect(lambda _=False, x=nm: pick_accent(x))
        ac_btns[nm] = b; ac_row.addWidget(b)
    ac_row.addStretch()
    refresh_ac()
    lay.addLayout(ac_row)
    desc(t("テーマ・アクセント色は再起動後に全体へ反映されます。"))

    # ── マウスホイール ──
    sub(t("🖱  マウスホイール"))
    wheel_row = QHBoxLayout(); wheel_row.setSpacing(6)
    zoom_btn = ToggleBtn(t("拡大・縮小"), s.wheel_mode == "zoom", h=30)
    page_btn = ToggleBtn(t("ページ送り"), s.wheel_mode == "page", h=30)

    def set_wheel(mode):
        s.wheel_mode = mode; s.save()
        zoom_btn.set_checked(mode == "zoom", silent=True)
        page_btn.set_checked(mode == "page", silent=True)
    zoom_btn.set_callback(lambda _: set_wheel("zoom"))
    page_btn.set_callback(lambda _: set_wheel("page"))
    wheel_row.addWidget(zoom_btn); wheel_row.addWidget(page_btn); wheel_row.addStretch()
    lay.addLayout(wheel_row)
    desc(t("「ページ送り」では下スクロールで前のページ、上で次のページに進みます。"))

    # ── 上下ドラッグでズーム（マンガミーヤ式）──
    dz_row = QHBoxLayout(); dz_row.setSpacing(6)
    dz_btn = ToggleBtn(t("上下ドラッグで拡大縮小"), getattr(s, "drag_zoom", True), h=30)

    def set_dz(v):
        s.drag_zoom = v; s.save()
    dz_btn.set_callback(set_dz)
    dz_row.addWidget(dz_btn); dz_row.addStretch()
    lay.addLayout(dz_row)
    desc(t("画面を上下にドラッグして無段階に拡大・縮小します（ポインタ位置を中心に拡大）。"))

    # ── 本を開いたとき ──
    sub(t("📖  本を開いたとき"))
    rm = getattr(s, "resume_mode", "continue")
    resume_row = QHBoxLayout(); resume_row.setSpacing(6)
    cont_btn = ToggleBtn(t("続きから"), rm == "continue", h=30)
    ask_btn  = ToggleBtn(t("毎回確認"), rm == "ask", h=30)
    start_btn = ToggleBtn(t("最初から"), rm == "start", h=30)

    def set_resume(mode):
        s.resume_mode = mode; s.save()
        cont_btn.set_checked(mode == "continue", silent=True)
        ask_btn.set_checked(mode == "ask", silent=True)
        start_btn.set_checked(mode == "start", silent=True)
    cont_btn.set_callback(lambda _: set_resume("continue"))
    ask_btn.set_callback(lambda _: set_resume("ask"))
    start_btn.set_callback(lambda _: set_resume("start"))
    resume_row.addWidget(cont_btn); resume_row.addWidget(ask_btn)
    resume_row.addWidget(start_btn); resume_row.addStretch()
    lay.addLayout(resume_row)
    desc(t("「続きから」は前回の続きを開きます（最初に戻るには「最初」ボタンやHomeキー）。"))

    # ── タグ ──
    sub(t("🏷  タグ"))
    at_row = QHBoxLayout(); at_row.setSpacing(6)
    at_btn = ToggleBtn(t("追加時に自動タグ付け（実験的）"), getattr(s, "auto_tag_on_add", False), h=30)

    def set_at(v):
        s.auto_tag_on_add = v; s.save()
    at_btn.set_callback(set_at)
    at_row.addWidget(at_btn); at_row.addStretch()
    lay.addLayout(at_row)
    desc(t("本を追加したとき、ファイル名から作者・サークル・原作・イベントを自動でタグ付けします。"))

    # ── データ管理 ──
    sub(t("データ管理"))
    lv = win.library_view
    action(t("📊  読書統計"), t("蔵書数・進捗・よく読む作者などを表示します。"),
           lambda: ReadingStatsDialog(win.library, dlg).exec())
    action(t("🔁  重複を検出"), t("同じファイル名の本を見つけて整理します。"),
           lambda: (DuplicatesDialog(win.library, dlg).exec(), lv.refresh()))
    action(t("📂  フォルダ構成から本棚を作成"),
           t("選んだフォルダ直下の各サブフォルダを本棚として一括取り込みします。"),
           lambda: (dlg.accept(), win._import_folder_shelves()))
    action(t("🏷  タグの管理"), t("タグの名前変更・削除をまとめて行います。"),
           lambda: lv._open_tag_manager(dlg))
    action(t("💾  バックアップを保存"), t("本棚と設定を1つのファイルに書き出します。"), lv._backup)
    action(t("📥  バックアップから復元"),
           t("保存したバックアップを読み込みます（現在のデータは置き換わります）。"),
           lambda: lv._restore(dlg))
    action(t("🔄  アップデートを確認"),
           t("最新かどうかを確認します（公式サイトに接続します）。"),
           lambda: win.check_for_updates(manual=True))

    # ── 操作 / ヘルプ ──
    sub(t("操作・ヘルプ"))
    action(t("⌨ ショートカット設定"), "", lambda: show_shortcuts_dialog(s, dlg))
    action(t("ヘルプ・操作一覧"), "", lambda: show_help_dialog(dlg, s))

    row = QHBoxLayout(); row.setContentsMargins(20, 8, 20, 14); row.addStretch()
    close = QPushButton(t("閉じる")); close.setObjectName("close")
    close.clicked.connect(dlg.accept)
    row.addWidget(close); outer.addLayout(row)
    dlg.exec()


class FlowLayout(QLayout):
    """折り返し（フロー）レイアウト。タグのチップを並べるのに使う。"""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self._items:
            w, h = it.sizeHint().width(), it.sizeHint().height()
            if x + w > rect.right() and line_h > 0:
                x = rect.x(); y += line_h + sp; line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + sp
            line_h = max(line_h, h)
        return y + line_h - rect.y()


class TagEditDialog(QDialog):
    """既存タグをサジェスト表示するタグ編集ダイアログ。

    既存タグはチップとして並び、クリックで追加/解除。新規タグは下の欄から追加する。
    """

    CHIP_QSS = ("QPushButton{background:#2b2539;color:#bbb;border:1px solid #463d63;"
                "border-radius:13px;padding:5px 14px;font-size:12px;}"
                "QPushButton:hover{background:#3a3251;color:#eee;}"
                "QPushButton:checked{background:#a06cff;color:white;border-color:#a06cff;}")

    def __init__(self, current_tags, all_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("タグを編集"))
        self.setMinimumWidth(480)
        self._selected = list(dict.fromkeys(str(t) for t in current_tags))
        self._chips: dict[str, QPushButton] = {}
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QLineEdit { background:#2b2539; color:#ddd; border:1px solid #463d63;
                        border-radius:10px; padding:5px 8px; font-size:13px; }
            QLineEdit:focus { border-color:#a06cff; }
            QScrollArea { border:1px solid #393350; border-radius:12px; background:#1f1a29; }
            QPushButton#primary { background:#a06cff; color:white; border:none;
                                  border-radius:10px; padding:7px 24px; font-size:13px; }
            QPushButton#primary:hover { background:#b488ff; }
            QPushButton#flat { background:#322b45; color:#ddd; border:1px solid #463d63;
                               border-radius:10px; padding:6px 16px; font-size:12px; }
            QPushButton#flat:hover { background:#423a5a; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(10)

        lay.addWidget(QLabel(t("タグをクリックで追加 / 解除。新しいタグは下の欄から追加できます。")))

        # 既存タグ＋現在のタグをチップとして表示（折り返し）
        host = QWidget(); host.setStyleSheet("background:transparent;")
        self._flow = FlowLayout(host, spacing=8)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(host)
        scroll.setMinimumHeight(150)
        lay.addWidget(scroll)
        for tag in dict.fromkeys(list(self._selected) + [str(x) for x in all_tags]):
            self._add_chip(tag)
        if not self._chips:
            self._empty_lbl = QLabel(t("（まだタグがありません。下から追加してください）"))
            self._empty_lbl.setStyleSheet("color:#777;background:transparent;")
            self._flow.addWidget(self._empty_lbl)

        # 新規タグ入力（既存タグの補完つき）
        row = QHBoxLayout(); row.setSpacing(6)
        self._new_edit = QLineEdit(); self._new_edit.setPlaceholderText(t("新しいタグを入力して Enter"))
        comp = QCompleter(sorted({str(x) for x in all_tags}), self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self._new_edit.setCompleter(comp)
        self._new_edit.returnPressed.connect(self._add_new)
        add_btn = QPushButton(t("＋ 追加")); add_btn.setObjectName("flat")
        add_btn.clicked.connect(self._add_new)
        row.addWidget(self._new_edit, 1); row.addWidget(add_btn)
        lay.addLayout(row)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton(t("キャンセル")); cancel.setObjectName("flat")
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t("保存")); ok.setObjectName("primary"); ok.clicked.connect(self.accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        lay.addLayout(btns)

    def _add_chip(self, tag: str) -> QPushButton:
        tag = tag.strip()
        if not tag or tag in self._chips:
            return self._chips.get(tag)
        if getattr(self, "_empty_lbl", None) is not None:
            self._empty_lbl.deleteLater(); self._empty_lbl = None
        b = QPushButton(tag); b.setCheckable(True); b.setChecked(tag in self._selected)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setStyleSheet(self.CHIP_QSS)
        b.toggled.connect(lambda on, t=tag: self._on_toggle(t, on))
        self._flow.addWidget(b)
        self._chips[tag] = b
        return b

    def _on_toggle(self, tag: str, on: bool):
        if on and tag not in self._selected:
            self._selected.append(tag)
        elif not on and tag in self._selected:
            self._selected.remove(tag)

    def _add_new(self):
        t = self._new_edit.text().strip()
        if not t:
            return
        self._new_edit.clear()
        b = self._add_chip(t)
        if b is not None:
            b.setChecked(True)   # toggled シグナルで _selected に追加される

    def result_tags(self) -> list[str]:
        return list(self._selected)


class TagPopup(QFrame):
    """本に付いたタグを一覧表示するポップアップ。

    タグ名クリックで絞り込みトグル、右端の「✕」でその本からタグを解除。
    """
    filter_toggled = Signal(str)
    tag_removed    = Signal(str)
    edit_requested = Signal()

    def __init__(self, tags, active_filter, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._active = set(active_filter)
        self._rows: dict[str, tuple] = {}
        self.setStyleSheet("QFrame{background:#262032;border:1px solid #463d63;border-radius:14px;}")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 8, 8, 8); self._lay.setSpacing(4)

        hdr = QLabel(t("🏷 この本のタグ"))
        hdr.setStyleSheet("color:#bfa6ff;font-size:12px;font-weight:bold;"
                          "background:transparent;border:none;padding:2px 4px;")
        self._lay.addWidget(hdr)

        for tag in tags:
            self._add_row(tag)

        sep = QLabel(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#393350;border:none;")
        self._lay.addWidget(sep)
        edit = QPushButton(t("タグを編集…"))
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setStyleSheet("QPushButton{background:#322b45;color:#ddd;border:1px solid #463d63;"
                           "border-radius:10px;padding:5px 10px;font-size:12px;}"
                           " QPushButton:hover{background:#423a5a;}")
        edit.clicked.connect(self.edit_requested.emit)
        self._lay.addWidget(edit)
        self.adjustSize()

    def _add_row(self, tag: str):
        row = QWidget(); row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        name = QPushButton(self._name_text(tag))
        name.setCursor(Qt.CursorShape.PointingHandCursor)
        name.setMinimumWidth(170)
        name.setStyleSheet("QPushButton{background:#2b2539;color:#ddd;border:1px solid #463d63;"
                           "border-radius:10px;padding:5px 10px;font-size:12px;text-align:left;}"
                           " QPushButton:hover{background:#3a3251;}")
        name.clicked.connect(lambda _=False, t=tag: self._on_name(t))
        x = QPushButton("✕"); x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setToolTip(t("この本からタグを外す"))
        x.setStyleSheet("QPushButton{background:#3a2a2a;color:#e88;border:1px solid #663333;"
                        "border-radius:10px;font-size:12px;} "
                        "QPushButton:hover{background:#c42b1c;color:white;}")
        x.clicked.connect(lambda _=False, t=tag: self._on_remove(t))
        h.addWidget(name, 1); h.addWidget(x)
        self._lay.addWidget(row)
        self._rows[tag] = (row, name)

    def _name_text(self, tag: str) -> str:
        return ("✓ " if tag in self._active else "    ") + tag

    def _on_name(self, tag: str):
        self._active.discard(tag) if tag in self._active else self._active.add(tag)
        row, name = self._rows[tag]
        name.setText(self._name_text(tag))
        self.filter_toggled.emit(tag)

    def _on_remove(self, tag: str):
        self.tag_removed.emit(tag)
        self._active.discard(tag)
        row, _ = self._rows.pop(tag, (None, None))
        if row is not None:
            row.setParent(None); row.deleteLater()
        if not self._rows:
            self.close()
        else:
            QTimer.singleShot(0, self.adjustSize)


class TagManagerDialog(QDialog):
    """全タグの名前変更・削除を行う管理ダイアログ。"""

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle(t("タグの管理"))
        self.setMinimumSize(440, 440)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QScrollArea { border:1px solid #393350; border-radius:12px; background:#1f1a29; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:5px 12px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#del:hover { background:#c42b1c; color:white; border-color:#c42b1c; }
            QPushButton#close { background:#a06cff; color:white; border:none; padding:7px 24px; }
            QPushButton#close:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 18, 18, 16); lay.setSpacing(10)
        lay.addWidget(QLabel(t("タグの名前変更・削除ができます（すべての本に反映されます）。")))

        auto_row = QHBoxLayout()
        auto_btn = QPushButton(t("🏷 ファイル名から自動タグ付け（実験的）"))
        auto_btn.clicked.connect(self._auto_tag)
        auto_row.addWidget(auto_btn); auto_row.addStretch()
        lay.addLayout(auto_row)

        self._host = QWidget(); self._host.setStyleSheet("background:transparent;")
        self._rows_lay = QVBoxLayout(self._host)
        self._rows_lay.setContentsMargins(6, 6, 6, 6); self._rows_lay.setSpacing(6)
        self._rows_lay.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self._host)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close"); close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)
        self._build()

    def _build(self):
        # 既存の行を撤去（末尾の stretch は残す）
        while self._rows_lay.count() > 1:
            it = self._rows_lay.takeAt(0)
            w = it.widget()
            if w is not None: w.deleteLater()
        tags = self.library.all_tags()
        if not tags:
            empty = QLabel(t("タグがありません。")); empty.setStyleSheet("color:#777;background:transparent;")
            self._rows_lay.insertWidget(0, empty)
            return
        for i, tag in enumerate(tags):
            row = QWidget(); row.setStyleSheet("background:transparent;")
            h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            name = QLabel(tag); name.setStyleSheet(
                "color:#ddd;font-size:13px;background:#2b2539;border:1px solid #463d63;"
                "border-radius:10px;padding:6px 10px;")
            ren = QPushButton(t("名前変更")); ren.clicked.connect(lambda _=False, x=tag: self._rename(x))
            dele = QPushButton(t("削除")); dele.setObjectName("del")
            dele.clicked.connect(lambda _=False, x=tag: self._delete(x))
            h.addWidget(name, 1); h.addWidget(ren); h.addWidget(dele)
            self._rows_lay.insertWidget(i, row)

    def _auto_tag(self):
        AutoTagDialog(self.library, self).exec()
        self._build()   # 追加されたタグを一覧へ反映

    def _rename(self, tag: str):
        new, ok = QInputDialog.getText(self, t("タグの名前変更"), t("新しいタグ名:"), text=tag)
        if ok and new.strip():
            self.library.rename_tag(tag, new.strip()); self._build()

    def _delete(self, tag: str):
        if QMessageBox.question(self, t("タグの削除"),
                                t("タグ「{tag}」を全ての本から削除しますか？").format(tag=tag),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            self.library.delete_tag(tag); self._build()


class AutoTagDialog(QDialog):
    """ファイル名から自動タグ付け（同人命名規則）。プレビューしてから一括適用する。"""

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self._mapping = {}
        self.setWindowTitle(t("ファイル名から自動タグ付け（実験的）"))
        self.setMinimumSize(480, 520)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QCheckBox { color:#ddd; font-size:13px; background:transparent; }
            QScrollArea { border:1px solid #393350; border-radius:12px; background:#1f1a29; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:6px 14px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#apply { background:#a06cff; color:white; border:none; padding:8px 24px; }
            QPushButton#apply:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        lay.addWidget(QLabel(t("ファイル名から作者・サークル・原作・イベント等を抽出してタグを付けます。\n"
                               "既存のタグは消さず追加するだけです。")))
        note = QLabel(t("※ 実験的機能です。ファイル名の付け方によっては誤って抽出することがあります。"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#ffc107;font-size:12px;background:transparent;")
        lay.addWidget(note)

        # 抽出する種類
        cb_row = QHBoxLayout(); cb_row.setSpacing(14)
        self._cb_artist = QCheckBox(t("作者・サークル")); self._cb_artist.setChecked(True)
        self._cb_parody = QCheckBox(t("原作")); self._cb_parody.setChecked(True)
        self._cb_event = QCheckBox(t("イベント・その他")); self._cb_event.setChecked(True)
        self._cb_folder = QCheckBox(t("親フォルダ名")); self._cb_folder.setChecked(False)
        self._cb_prefix = QCheckBox(t("接頭辞をつける（作者: など）")); self._cb_prefix.setChecked(True)
        for c in (self._cb_artist, self._cb_parody, self._cb_event, self._cb_folder):
            c.stateChanged.connect(self._recompute); cb_row.addWidget(c)
        cb_row.addStretch()
        lay.addLayout(cb_row)
        self._cb_prefix.stateChanged.connect(self._recompute)
        lay.addWidget(self._cb_prefix)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color:#bfa6ff;font-size:13px;font-weight:bold;background:transparent;")
        lay.addWidget(self._summary)

        # 付くタグの一覧（種類別・冊数つき）
        self._host = QWidget(); self._host.setStyleSheet("background:transparent;")
        self._rows = QVBoxLayout(self._host)
        self._rows.setContentsMargins(8, 8, 8, 8); self._rows.setSpacing(3)
        self._rows.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self._host)
        scroll.setStyleSheet(scroll.styleSheet() +
                             "QScrollBar:vertical{background:#18151f;width:14px;}"
                             "QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;}"
                             "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        lay.addWidget(scroll, 1)

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton(t("キャンセル")); cancel.clicked.connect(self.reject)
        self._apply_btn = QPushButton(t("適用")); self._apply_btn.setObjectName("apply")
        self._apply_btn.clicked.connect(self._apply)
        row.addWidget(cancel); row.addWidget(self._apply_btn)
        lay.addLayout(row)

        self._recompute()

    def _types(self):
        from auto_tag import T_ARTIST, T_PARODY, T_EVENT, T_FOLDER
        s = set()
        if self._cb_artist.isChecked(): s.add(T_ARTIST)
        if self._cb_parody.isChecked(): s.add(T_PARODY)
        if self._cb_event.isChecked(): s.add(T_EVENT)
        if self._cb_folder.isChecked(): s.add(T_FOLDER)
        return s

    def _recompute(self):
        import auto_tag
        books = [b for shelf in self.library.shelves for b in shelf["books"]]
        self._mapping, counts = auto_tag.propose(books, self._types(), self._cb_prefix.isChecked())
        n_books = len(self._mapping)
        n_tags = len(counts)
        self._summary.setText(t("{books} 冊に {tags} 種類のタグを付けます").format(books=n_books, tags=n_tags))
        self._apply_btn.setEnabled(n_books > 0)
        # 一覧を作り直し（冊数の多い順、上位300件）
        while self._rows.count() > 1:
            it = self._rows.takeAt(0); w = it.widget()
            if w is not None: w.deleteLater()
        if not counts:
            empty = QLabel(t("付けられるタグが見つかりませんでした。"))
            empty.setStyleSheet("color:#777;background:transparent;")
            self._rows.insertWidget(0, empty); return
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for i, (tag, cnt) in enumerate(ordered[:300]):
            lbl = QLabel(f"{tag}　— {cnt}")
            lbl.setStyleSheet("color:#ddd;font-size:12px;background:#2b2539;"
                              "border:1px solid #463d63;border-radius:8px;padding:4px 8px;")
            self._rows.insertWidget(i, lbl)

    def _apply(self):
        if not self._mapping:
            return
        n = self.library.add_tags_bulk(self._mapping)
        QMessageBox.information(self, t("完了"),
                               t("{n} 冊にタグを付けました。").format(n=n))
        self.accept()


class _CheckTree(QTreeWidget):
    """子（タグ）行はチェックボックスでなく文字部分をクリックしても選択トグルできる木。"""

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if (item is not None and item.parent() is not None
                and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable)):
            # テキスト/チェックボックスどちらをクリックしても1回だけトグル（二重トグル防止）
            new = (Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                   else Qt.CheckState.Checked)
            item.setCheckState(0, new)
            return
        super().mousePressEvent(e)


class DuplicatesDialog(QDialog):
    """同名ファイルの重複を検出して、不要な方を選んで削除する。"""

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle(t("🔁 重複を検出"))
        self.setMinimumSize(560, 560)
        self.setStyleSheet("""
            QDialog{background:#262032;} QLabel{color:#ddd;background:transparent;}
            QTreeWidget{background:#1f1a29;color:#ddd;border:1px solid #393350;border-radius:12px;
                        font-size:12px;outline:none;}
            QTreeWidget::item{padding:3px;}
            QScrollBar:vertical{background:#18151f;width:14px;}
            QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
            QPushButton{background:#322b45;color:#ddd;border:1px solid #463d63;border-radius:10px;
                        padding:6px 14px;font-size:12px;} QPushButton:hover{background:#423a5a;}
            QPushButton#del{background:#c4452f;color:white;border:none;}
            QPushButton#del:hover{background:#e0573f;}
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        self._info = QLabel(""); lay.addWidget(self._info)
        self._tree = QTreeWidget(); self._tree.setHeaderHidden(True)
        lay.addWidget(self._tree, 1)
        row = QHBoxLayout()
        hint = QLabel(t("※ 各グループで残す1冊以外にチェックが入っています"))
        hint.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        row.addWidget(hint); row.addStretch()
        close = QPushButton(t("閉じる")); close.clicked.connect(self.accept)
        self._del = QPushButton(t("チェックした本を削除")); self._del.setObjectName("del")
        self._del.clicked.connect(self._delete_checked)
        row.addWidget(close); row.addWidget(self._del)
        lay.addLayout(row)
        self._build()

    def _build(self):
        self._tree.clear()
        groups = self.library.find_duplicates()
        n_groups = len(groups)
        n_books = sum(len(v) for v in groups.values())
        self._info.setText(t("重複の可能性: {g} グループ / {b} 冊").format(g=n_groups, b=n_books)
                           if groups else t("重複は見つかりませんでした。"))
        self._del.setEnabled(bool(groups))
        for name, items in sorted(groups.items()):
            parent = QTreeWidgetItem(self._tree, [f"{name}  ({len(items)})"])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for i, b in enumerate(items):
                shelf = self._shelf_name_of(b["id"])
                ch = QTreeWidgetItem(parent, [f"{b.get('title', '')}  —  {shelf}\n{b['path']}"])
                ch.setFlags(ch.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ch.setData(0, Qt.ItemDataRole.UserRole, b["id"])
                # 既定: 各グループ先頭は残す（チェックしない）、残りは削除候補
                ch.setCheckState(0, Qt.CheckState.Unchecked if i == 0 else Qt.CheckState.Checked)
            parent.setExpanded(True)

    def _shelf_name_of(self, bid):
        for s in self.library.shelves:
            if any(b["id"] == bid for b in s["books"]):
                return s["name"]
        return ""

    def _delete_checked(self):
        ids = set()
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            for j in range(p.childCount()):
                ch = p.child(j)
                if ch.checkState(0) == Qt.CheckState.Checked:
                    ids.add(ch.data(0, Qt.ItemDataRole.UserRole))
        if not ids:
            return
        if QMessageBox.question(self, t("削除確認"),
                                t("チェックした {n} 冊を本棚から削除しますか？\n（元のファイルは削除されません）").format(n=len(ids)),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) == QMessageBox.StandardButton.Yes:
            self.library.remove_many_everywhere(ids)
            self._build()


class ReadingStatsDialog(QDialog):
    """読書統計のダッシュボード（蔵書・進捗・よく読む作者/原作など）。"""

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("📊 読書統計"))
        self.setMinimumSize(440, 520)
        self.setStyleSheet("QDialog{background:#262032;} "
                           "QTextBrowser{background:#1f1a29;color:#ddd;border:1px solid #393350;"
                           "border-radius:12px;font-size:13px;padding:10px;} "
                           "QPushButton{background:#a06cff;color:white;border:none;border-radius:10px;"
                           "padding:8px 24px;font-size:12px;} QPushButton:hover{background:#b488ff;}")
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        view = QTextBrowser(); view.setOpenExternalLinks(False)
        view.setHtml(self._build_html(library))
        lay.addWidget(view, 1)
        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)

    @staticmethod
    def _build_html(library) -> str:
        from collections import Counter
        books = library._unique_books()
        total = len(books)
        read = sum(1 for b in books if library.is_read(b))
        prog = sum(1 for b in books if library.in_progress(b))
        unread = sum(1 for b in books if not b.get("last_opened"))
        favs = sum(1 for b in books if b.get("favorite"))
        total_pages = sum(int(b.get("total_pages", 0) or 0) for b in books)
        read_pages = sum(int(b.get("total_pages", 0) or 0) if library.is_read(b)
                         else int(b.get("last_page", 0) or 0) for b in books)
        days = len({b.get("last_opened") for b in books if b.get("last_opened")})
        tag_kinds = len(library.all_tags())
        artist = Counter(); parody = Counter()
        for b in books:
            for tg in b.get("tags", []):
                if tg.startswith("作者:"): artist[tg[3:]] += 1
                elif tg.startswith("原作:"): parody[tg[3:]] += 1

        def top(counter, n=5):
            if not counter:
                return "<i style='color:#777;'>—</i>"
            return "<br>".join(f"{i + 1}. {k} <span style='color:#8a7fa6;'>({v})</span>"
                               for i, (k, v) in enumerate(counter.most_common(n)))

        ac = "#bfa6ff"
        return f"""
        <h2 style='color:{ac};'>📚 蔵書</h2>
        <p>登録冊数: <b>{total}</b> 冊<br>
        読了: <b>{read}</b> / 読みかけ: <b>{prog}</b> / 未読: <b>{unread}</b><br>
        ★お気に入り: <b>{favs}</b> / タグ種類: <b>{tag_kinds}</b></p>
        <h2 style='color:{ac};'>📖 ページ</h2>
        <p>総ページ数: <b>{total_pages:,}</b> ページ<br>
        読んだページ数: <b>{read_pages:,}</b> ページ<br>
        読書した日数: <b>{days}</b> 日</p>
        <h2 style='color:{ac};'>✍️ よく読む作者</h2>
        <p>{top(artist)}</p>
        <h2 style='color:{ac};'>🎯 よく読む原作</h2>
        <p>{top(parody)}</p>
        """


class TagFilterDialog(QDialog):
    """タグ絞り込み用のウィンドウ。種類ごとに折りたたみ＋検索＋スクロール。

    接頭辞（作者:/サークル:/原作:/イベント:）でカテゴリにまとめ、見出しを開くと
    その一覧（例: イベント → C103 …）が出る。タグが数百〜数千でも辿りやすい。
    複数選択（いずれかに一致でヒット）＋「★お気に入りのみ」。
    """
    # (接頭辞, カテゴリ表示名) — この順で見出しを並べる
    _GROUPS = (("作者:", "作者"), ("サークル:", "サークル"),
               ("原作:", "原作"), ("イベント:", "イベント"), ("フォルダ:", "フォルダ"))
    _OTHER = "その他"
    # 選択中タグのチップ（はっきり色枠／ホバーで赤＝クリックで解除を示唆）
    SEL_CHIP_QSS = ("QPushButton{background:#a06cff;color:white;border:1px solid #b488ff;"
                    "border-radius:12px;padding:5px 12px;font-size:12px;}"
                    "QPushButton:hover{background:#c4452f;border-color:#e06a52;}")

    def __init__(self, all_tags, selected, fav_on, parent=None, expanded=None, scroll=0,
                 read_state="all", tag_match="or"):
        super().__init__(parent)
        self.result_tags = set(selected)
        self.result_fav = bool(fav_on)
        self.result_read = read_state if read_state in ("all", "unread", "read") else "all"
        self.result_match = tag_match if tag_match in ("or", "and") else "or"
        self._read = self.result_read
        self._match = self.result_match
        self._init_expanded = expanded     # 前回開いていたカテゴリ名の集合（None=初回）
        self._init_scroll = int(scroll or 0)
        self.setWindowTitle(t("絞り込み"))
        self.setMinimumSize(380, 560)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QCheckBox { color:#ddd; font-size:13px; background:transparent; }
            QLineEdit { background:#2b2539; color:#ddd; border:1px solid #463d63;
                        border-radius:10px; padding:6px 10px; font-size:13px; }
            QLineEdit:focus { border-color:#a06cff; }
            QTreeWidget { background:#1f1a29; color:#ddd; border:1px solid #393350;
                          border-radius:12px; font-size:13px; outline:none; padding:4px; }
            QTreeWidget::item { padding:5px 4px; }
            QTreeWidget::item:hover { background:#221d31; }
            QScrollBar:vertical { background:#18151f; width:14px; }
            QScrollBar::handle:vertical { background:#393350; border-radius:7px; min-height:40px; }
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:6px 14px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#apply { background:#a06cff; color:white; border:none; padding:8px 24px; }
            QPushButton#apply:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)

        self._fav_cb = QCheckBox(t("★ お気に入りのみ")); self._fav_cb.setChecked(self.result_fav)
        lay.addWidget(self._fav_cb)

        # 読書状態（未読/既読）
        rs_row = QHBoxLayout(); rs_row.setSpacing(6)
        rs_lbl = QLabel(t("状態:")); rs_lbl.setStyleSheet("color:#8a7fa6;background:transparent;")
        rs_row.addWidget(rs_lbl)
        self._rs_all = ToggleBtn(t("すべて"), self._read == "all", h=28, font_size=12)
        self._rs_unread = ToggleBtn(t("未読"), self._read == "unread", h=28, font_size=12)
        self._rs_read = ToggleBtn(t("既読"), self._read == "read", h=28, font_size=12)

        def pick_read(state):
            self._read = state
            self._rs_all.set_checked(state == "all", silent=True)
            self._rs_unread.set_checked(state == "unread", silent=True)
            self._rs_read.set_checked(state == "read", silent=True)
        self._rs_all.set_callback(lambda _: pick_read("all"))
        self._rs_unread.set_callback(lambda _: pick_read("unread"))
        self._rs_read.set_callback(lambda _: pick_read("read"))
        self._pick_read = pick_read
        for b in (self._rs_all, self._rs_unread, self._rs_read):
            rs_row.addWidget(b)
        rs_row.addStretch()
        lay.addLayout(rs_row)

        # タグの一致条件（いずれか=OR / すべて=AND）
        m_row = QHBoxLayout(); m_row.setSpacing(6)
        m_lbl = QLabel(t("タグ一致:")); m_lbl.setStyleSheet("color:#8a7fa6;background:transparent;")
        m_row.addWidget(m_lbl)
        self._m_or = ToggleBtn(t("いずれか"), self._match == "or", h=28, font_size=12)
        self._m_and = ToggleBtn(t("すべて"), self._match == "and", h=28, font_size=12)

        def pick_match(m):
            self._match = m
            self._m_or.set_checked(m == "or", silent=True)
            self._m_and.set_checked(m == "and", silent=True)
        self._m_or.set_callback(lambda _: pick_match("or"))
        self._m_and.set_callback(lambda _: pick_match("and"))
        m_row.addWidget(self._m_or); m_row.addWidget(self._m_and); m_row.addStretch()
        lay.addLayout(m_row)

        self._search = QLineEdit(); self._search.setPlaceholderText(t("🔍 タグを検索..."))
        self._search.textChanged.connect(self._filter)
        lay.addWidget(self._search)

        self._count = QLabel("")
        self._count.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(self._count)

        # 選択中のタグ：クリックで解除できる色付きボタン（チップ）を折り返し表示
        self._sel_host = QWidget(); self._sel_host.setStyleSheet("background:transparent;")
        self._sel_flow = FlowLayout(self._sel_host, spacing=6)
        sel_scroll = QScrollArea(); sel_scroll.setWidgetResizable(True)
        sel_scroll.setWidget(self._sel_host); sel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sel_scroll.setMaximumHeight(110)
        sel_scroll.setStyleSheet(
            "QScrollArea{background:#231d33;border:1px solid #463d63;border-radius:10px;}"
            "QScrollBar:vertical{background:#18151f;width:12px;}"
            "QScrollBar::handle:vertical{background:#393350;border-radius:6px;min-height:30px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        lay.addWidget(sel_scroll)

        self._total = 0
        self._tree = _CheckTree(); self._tree.setHeaderHidden(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._build_tree(all_tags)
        lay.addWidget(self._tree, 1)

        # 入力サジェスト（かな/全半角を区別しない部分一致ポップアップ）
        self._search.setCompleter(make_fold_completer(self._labels, self))

        row = QHBoxLayout()
        clear = QPushButton(t("すべて解除")); clear.clicked.connect(self._clear)
        self._selectall_btn = QPushButton(t("全て選択"))
        self._selectall_btn.setToolTip(t("検索でヒットしたタグをすべて選択"))
        self._selectall_btn.clicked.connect(self._select_visible)
        self._selectall_btn.setEnabled(False)   # 検索中だけ有効
        row.addWidget(clear); row.addWidget(self._selectall_btn); row.addStretch()
        cancel = QPushButton(t("キャンセル")); cancel.clicked.connect(self.reject)
        apply = QPushButton(t("適用")); apply.setObjectName("apply"); apply.clicked.connect(self._apply)
        row.addWidget(cancel); row.addWidget(apply)
        lay.addLayout(row)

        self._search.setFocus()
        self._update_count()
        # レイアウト確定後に前回のスクロール位置を復元（範囲未確定に備え2回）
        if self._init_scroll:
            QTimer.singleShot(0, self._restore_scroll)
            QTimer.singleShot(40, self._restore_scroll)

    def _restore_scroll(self):
        bar = self._tree.verticalScrollBar()
        bar.setValue(max(0, min(self._init_scroll, bar.maximum())))

    def current_scroll(self) -> int:
        return self._tree.verticalScrollBar().value()

    def current_expanded(self) -> set:
        """現在開いているカテゴリ名の集合（次回の復元用）。"""
        out = set()
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            if p.isExpanded():
                cat = p.data(0, Qt.ItemDataRole.UserRole)
                if cat:
                    out.add(cat)
        return out

    def _categorize(self, tag: str):
        for pfx, cat in self._GROUPS:
            if tag.startswith(pfx):
                return cat, tag[len(pfx):]
        return self._OTHER, tag

    def _build_tree(self, all_tags):
        buckets = {cat: [] for _, cat in self._GROUPS}
        buckets[self._OTHER] = []
        for tag in all_tags:
            cat, label = self._categorize(tag)
            buckets[cat].append((label, tag))
        self._total = len(all_tags)
        self._labels = []   # サジェスト用（表示ラベル）
        order = [c for _, c in self._GROUPS] + [self._OTHER]
        self._tree.blockSignals(True)
        for cat in order:
            items = buckets.get(cat)
            if not items:
                continue
            parent = QTreeWidgetItem(self._tree, [f"{cat}  ({len(items)})"])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)   # 見出し（チェック不可）
            parent.setData(0, Qt.ItemDataRole.UserRole, cat)   # カテゴリ名（開閉記憶用）
            has_checked = False
            for label, tag in sorted(items, key=lambda x: x[0].lower()):
                ch = QTreeWidgetItem(parent, [label])
                ch.setFlags(ch.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                ch.setData(0, Qt.ItemDataRole.UserRole, tag)
                ch.setData(0, Qt.ItemDataRole.UserRole + 1, fold_text(label + " " + tag))  # 検索キー
                checked = tag in self.result_tags
                ch.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                has_checked = has_checked or checked
                self._labels.append(label)
            # 前回開いていたカテゴリは開く（初回は選択中タグのあるカテゴリだけ）
            if self._init_expanded is None:
                parent.setExpanded(has_checked)
            else:
                parent.setExpanded(cat in self._init_expanded)
        self._tree.blockSignals(False)

    def _filter(self, text):
        q = fold_text(text.strip())   # ひらがな/カタカナ・全角/半角・大小を吸収
        self._selectall_btn.setEnabled(bool(q))   # 「全て選択」は検索中だけ有効
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            any_vis = False
            for j in range(parent.childCount()):
                ch = parent.child(j)
                key = ch.data(0, Qt.ItemDataRole.UserRole + 1) or ""
                vis = (not q) or (q in key)
                ch.setHidden(not vis)
                any_vis = any_vis or vis
            parent.setHidden(not any_vis)
            if q:
                parent.setExpanded(any_vis)            # 検索中はヒットしたカテゴリを開く
            else:
                parent.setExpanded(self._has_checked(parent))   # クリアで既定の畳み方へ

    def _has_checked(self, parent) -> bool:
        return any(parent.child(j).checkState(0) == Qt.CheckState.Checked
                   for j in range(parent.childCount()))

    def _on_item_clicked(self, item, _col):
        if item.parent() is None:        # 見出しクリックで開閉
            item.setExpanded(not item.isExpanded())

    def _on_item_changed(self, _item, _col):
        self._update_count()

    def _checked_tags(self) -> list:
        out = []
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            for j in range(p.childCount()):
                ch = p.child(j)
                if ch.checkState(0) == Qt.CheckState.Checked:
                    out.append(ch.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _update_count(self):
        chosen = self._checked_tags()
        self._count.setText(t("全 {total} タグ / 選択中 {n}").format(
            total=self._total, n=len(chosen)))
        self._rebuild_selected(chosen)

    def _rebuild_selected(self, chosen):
        # 既存チップを撤去
        while self._sel_flow.count():
            it = self._sel_flow.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        if not chosen:
            empty = QLabel(t("タグ未選択（タップして絞り込み）"))
            empty.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
            self._sel_flow.addWidget(empty)
            return
        for tag in chosen:
            b = QPushButton(tag + "  ✕")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(self.SEL_CHIP_QSS)
            b.setToolTip(t("クリックで解除"))
            b.clicked.connect(lambda _=False, x=tag: self._deselect(x))
            self._sel_flow.addWidget(b)

    def _deselect(self, tag):
        """選択中チップのクリックでそのタグのチェックを外す。"""
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            for j in range(p.childCount()):
                ch = p.child(j)
                if ch.data(0, Qt.ItemDataRole.UserRole) == tag:
                    ch.setCheckState(0, Qt.CheckState.Unchecked)  # itemChanged→再描画
                    return

    def _clear(self):
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            for j in range(p.childCount()):
                p.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)
        self._fav_cb.setChecked(False)
        self._pick_read("all")
        self._update_count()

    def _select_visible(self):
        """検索でヒット（表示中）のタグをまとめて選択する。"""
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            p = self._tree.topLevelItem(i)
            if p.isHidden():
                continue
            for j in range(p.childCount()):
                ch = p.child(j)
                if not ch.isHidden():
                    ch.setCheckState(0, Qt.CheckState.Checked)
        self._tree.blockSignals(False)
        self._update_count()

    def _apply(self):
        self.result_tags = set(self._checked_tags())
        self.result_fav = self._fav_cb.isChecked()
        self.result_read = self._read
        self.result_match = self._match
        self.accept()


class FlatBtn(QLabel):
    def __init__(self, text: str, h: int = 28, blue: bool = False, font_size: int = 12, parent=None):
        super().__init__(text, parent)
        self._h = h; self._blue = blue; self._font_size = font_size
        self._enabled_look = True
        self.setFixedHeight(h)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cb = None
        self._apply_style()

    def _apply_style(self):
        if not self._enabled_look:
            self.setStyleSheet(theme.btn_disabled_qss(self._h, self._font_size))
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._blue:
            self.setStyleSheet(theme.btn_accent_qss(self._h, self._font_size))
        else:
            self.setStyleSheet(theme.btn_qss(self._h, self._font_size))

    def set_enabled_look(self, enabled: bool):
        """位置を保ったまま有効/無効の見た目を切り替える（ツールバーのズレ防止）。"""
        if enabled == self._enabled_look:
            return
        self._enabled_look = enabled
        self._apply_style()

    def set_callback(self, cb): self._cb = cb
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._enabled_look and self._cb:
            self._cb()


class ToggleBtn(QLabel):
    def __init__(self, text: str, checked: bool = False, h: int = 28, font_size: int = 12, parent=None):
        super().__init__(text, parent)
        self._checked = checked
        self._cb = None
        self._font_size = font_size
        self.setFixedHeight(h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh()

    def set_callback(self, cb): self._cb = cb
    def is_checked(self) -> bool: return self._checked

    def set_checked(self, v: bool, silent: bool = False):
        self._checked = v; self._refresh()
        if not silent and self._cb: self._cb(v)

    def _refresh(self):
        fs = self._font_size
        h = self.height()
        if self._checked:
            self.setStyleSheet(theme.toggle_on_qss(h, fs))
        else:
            self.setStyleSheet(theme.toggle_off_qss(h, fs))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.set_checked(not self._checked)


class BookCard(QFrame):
    clicked           = Signal(str)
    remove_requested  = Signal(str)
    selection_toggled = Signal(str, bool)
    menu_requested    = Signal(str, QPoint)   # (book_id, global pos)
    favorite_clicked  = Signal(str)           # 右上の星をクリック
    tags_clicked      = Signal(str, QPoint)   # 左上のタグアイコンをクリック

    def __init__(self, book: dict, cw: int, ch: int, parent=None):
        super().__init__(parent)
        self.book_id = book["id"]
        self._cw, self._ch = cw, ch
        self._title = book["title"]
        self._favorite = bool(book.get("favorite", False))
        self._has_tags = bool(book.get("tags"))
        self._star_hover = False
        self._tag_hover = False
        self._last_opened = book.get("last_opened", "")
        total = book.get("total_pages", 0); last = book.get("last_page", 0)
        self._progress = int(last / total * 100) if total > 0 else 0
        self._px: QPixmap = QPixmap()
        self._selection_mode = False
        self._selected = False
        # 「既読(緑)」は一度でも開いた本（last_opened がある）
        self._has_read = bool(book.get("last_opened", ""))
        self._press_pos: QPoint | None = None
        self._moved = False
        self._press_on_star = False
        self._press_on_tag = False

        self.setFixedSize(cw + 4, ch + 4)
        self._ns = (f"BookCard{{background:{theme.BG_APP};border-radius:{theme.R_CARD}px;"
                    f"border:2px solid transparent;}}"
                    f" BookCard:hover{{border:2px solid {theme.ACCENT};}}")
        self._ss = (f"BookCard{{background:{theme.BG_APP};border-radius:{theme.R_CARD}px;"
                    f"border:2px solid {theme.BORDER_SOFT};}}")
        self._cs = (f"BookCard{{background:{theme.ACCENT_SEL_BG};border-radius:{theme.R_CARD}px;"
                    f"border:2px solid {theme.ACCENT};}}")
        self.setStyleSheet(self._ns)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)   # 星のホバー検出のため

        self._check = QLabel("✓", self)
        self._check.setFixedSize(24, 24); self._check.move(8, 8)
        self._check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check.setStyleSheet(f"background:{theme.ACCENT};color:white;border-radius:12px;font-size:14px;font-weight:bold;")
        self._check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._check.setVisible(False)

    def set_cover(self, px: QPixmap):
        if not px.isNull():
            self._px = px.scaled(self._cw, self._ch,
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width() - 4, self.height() - 4
        # 角丸にクリップして表紙・帯が角からはみ出さないようにする（ポップな丸み）
        from PySide6.QtCore import QRectF
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(2, 2, w, h), theme.R_CARD, theme.R_CARD)
        p.setClipPath(clip)
        p.fillRect(2, 2, w, h, QColor(theme.BG_APP))
        if not self._px.isNull():
            ix = 2 + (w - self._px.width()) // 2
            iy = 2 + (h - self._px.height()) // 2
            p.drawPixmap(ix, iy, self._px)
        else:
            f = QFont(); f.setPointSize(max(7, self._cw // 20))
            p.setFont(f); p.setPen(QColor(100, 100, 100))
            from PySide6.QtCore import QRect
            p.drawText(QRect(2, 2, w, h), Qt.AlignmentFlag.AlignCenter, t("読み込み中..."))
        ov_h = h // 3; ov_y = h - ov_h + 2
        # タイトル帯はグラデーションをやめ単色塗り（可読性向上）
        overlay = QColor(0, 90, 30, 150) if self._has_read else QColor(0, 0, 0, 145)
        p.fillRect(2, ov_y, w, ov_h, overlay)
        font = QFont(); font.setPointSize(max(8, self._cw // 18)); font.setBold(True)
        p.setFont(font); p.setPen(QColor(255, 255, 255))
        from PySide6.QtCore import QRect
        tr = QRect(6, ov_y + 4, w - 8, ov_h - 22)
        p.drawText(tr, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, self._title)
        if self._last_opened:
            font2 = QFont(); font2.setPointSize(max(7, self._cw // 22))
            p.setFont(font2); p.setPen(QColor(200, 200, 200, 200))
            dr = QRect(6, h - 18, w - 8, 16)
            p.drawText(dr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._last_opened)
        if self._progress > 0:
            bar_y = h - 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(60, 60, 60, 180)); p.drawRect(2, bar_y, w, 4)
            pw = int(w * self._progress / 100)
            p.setBrush(QColor(0xa0, 0x6c, 0xff, 230)); p.drawRect(2, bar_y, pw, 4)
        if self._has_tags:
            self._draw_tag_badge(p, 8, 8)
        self._draw_star(p)
        p.end()

    def _star_hit_rect(self):
        from PySide6.QtCore import QRect
        sz = max(16, self._cw // 9)
        # 描画位置より少し広めにしてクリックしやすくする
        return QRect(self.width() - 8 - sz - 4, 0, sz + 14, sz + 14)

    def _draw_star(self, p: QPainter):
        from PySide6.QtCore import QRect
        sz = max(16, self._cw // 9)
        rect = QRect(self.width() - 8 - sz, 5, sz, sz)
        f = QFont(); f.setPointSize(max(11, self._cw // 11)); p.setFont(f)
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(rect.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignCenter,
                   "★" if (self._favorite or self._star_hover) else "☆")
        if self._favorite:
            p.setPen(QColor(0xff, 0xc1, 0x07)); ch = "★"
        elif self._star_hover:
            p.setPen(QColor(0xff, 0xd9, 0x54)); ch = "★"
        else:
            p.setPen(QColor(255, 255, 255, 140)); ch = "☆"
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)

    def _tag_hit_rect(self):
        from PySide6.QtCore import QRect
        return QRect(4, 4, 30, 24)   # 左上のタグアイコン周辺（クリック判定）

    def _draw_tag_badge(self, p: QPainter, x: int, y: int):
        """左上に小さなタグ（ラベル）アイコンを描く。"""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPolygon
        w_, h_ = 22, 15
        poly = QPolygon([QPoint(x + 6, y), QPoint(x + w_, y), QPoint(x + w_, y + h_),
                         QPoint(x + 6, y + h_), QPoint(x, y + h_ // 2)])
        body = QColor(0x5f, 0xd4, 0xc8) if self._tag_hover else QColor(0x4d, 0xb6, 0xac)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 130)); p.drawPolygon(poly.translated(1, 1))   # 影
        p.setBrush(body); p.drawPolygon(poly)                                    # ティール
        p.setBrush(QColor(26, 26, 26)); p.drawEllipse(QPoint(x + 7, y + h_ // 2), 2, 2)

    def set_favorite(self, v: bool):
        self._favorite = bool(v); self.update()

    def set_tags(self, tags):
        self._has_tags = bool(tags); self.update()

    def set_selection_mode(self, v: bool):
        self._selection_mode = v
        if not v: self._selected = False; self._check.setVisible(False); self.setStyleSheet(self._ns)
        else: self.setStyleSheet(self._ss)

    def set_selected(self, v: bool):
        self._selected = v; self._check.setVisible(v)
        self.setStyleSheet(self._cs if v else self._ss)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint(); self._moved = False
            self._press_on_star = self._star_hit_rect().contains(self._press_pos)
            self._press_on_tag = self._has_tags and self._tag_hit_rect().contains(self._press_pos)
        elif e.button() == Qt.MouseButton.MiddleButton:
            e.ignore()

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            d = e.position().toPoint() - self._press_pos
            if abs(d.x()) > 6 or abs(d.y()) > 6: self._moved = True
        elif e.buttons() & Qt.MouseButton.MiddleButton:
            e.ignore()
        else:
            # ホバー：星・タグアイコンの上に来たら強調表示
            pos = e.position().toPoint()
            star = self._star_hit_rect().contains(pos)
            tag = self._has_tags and self._tag_hit_rect().contains(pos)
            if star != self._star_hover or tag != self._tag_hover:
                self._star_hover = star; self._tag_hover = tag; self.update()

    def leaveEvent(self, e):
        if self._star_hover or self._tag_hover:
            self._star_hover = False; self._tag_hover = False; self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            if not self._moved and self._press_on_tag:
                # タグアイコンクリック：付いているタグを表示
                self.tags_clicked.emit(self.book_id, e.globalPosition().toPoint())
            elif not self._moved and self._press_on_star:
                # 星クリック：選択/閲覧ではなくお気に入りトグル
                self.favorite_clicked.emit(self.book_id)
            elif not self._moved:
                if self._selection_mode:
                    self._selected = not self._selected
                    self.set_selected(self._selected)
                    self.selection_toggled.emit(self.book_id, self._selected)
                else:
                    self.clicked.emit(self.book_id)
            self._press_pos = None; self._moved = False
            self._press_on_star = False; self._press_on_tag = False
        elif e.button() == Qt.MouseButton.MiddleButton:
            e.ignore()

    def contextMenuEvent(self, e):
        if self._selection_mode: return
        # メニューの構築は本棚（本棚一覧やタグ情報を持つ LibraryView）側に任せる
        self.menu_requested.emit(self.book_id, e.globalPos())


class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("background:#1f1a29;")
        self._drag_pos = None
        self._overlay = False     # 全画面中：レイアウト外のオーバーレイか
        self._revealed = False    # オーバーレイが表示状態か
        self._slide_anim = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0); lay.setSpacing(0)

        self._title_lbl = QLabel("Piewer")
        self._title_lbl.setStyleSheet("color:#999;font-size:12px;background:transparent;")
        lay.addWidget(self._title_lbl); lay.addStretch()

        _norm = ("QPushButton{background:transparent;color:#aaa;border:none;font-size:14px;}"
                 " QPushButton:hover{background:#322b45;color:white;}")
        _close = ("QPushButton{background:transparent;color:#aaa;border:none;font-size:14px;}"
                  " QPushButton:hover{background:#c42b1c;color:white;}")

        self._help_btn  = QPushButton("?")
        self._fs_btn    = QPushButton("⛶")
        self._min_btn   = QPushButton("─")
        self._max_btn   = QPushButton("□")
        self._close_btn = QPushButton("✕")

        for btn, sty in [(self._help_btn, _norm), (self._fs_btn, _norm), (self._min_btn, _norm),
                         (self._max_btn, _norm), (self._close_btn, _close)]:
            btn.setFixedSize(46, 32)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(sty)
            lay.addWidget(btn)
        self._help_btn.setToolTip(t("ヘルプ・操作一覧"))

        self._help_btn.clicked.connect(
            lambda: show_help_dialog(self.window(), getattr(self.window(), "settings", None)))
        self._fs_btn.clicked.connect(self._toggle_fs)
        self._min_btn.clicked.connect(lambda: self.window().showMinimized())
        self._max_btn.clicked.connect(self._toggle_max)
        self._close_btn.clicked.connect(self.window().close)

    def set_title(self, title: str):
        self._title_lbl.setText(title)

    def retranslate(self):
        self._help_btn.setToolTip(t("ヘルプ・操作一覧"))

    def update_state_buttons(self):
        """ウィンドウ状態に合わせてボタンの見た目を更新する。
        全画面中は最大化ボタンを「全画面終了」ボタンに変え、?/⛶ は隠す。"""
        win = self.window()
        if getattr(win, "_fullscreen", False):
            self._help_btn.hide(); self._fs_btn.hide()
            self._max_btn.setText("⤡")
            self._max_btn.setToolTip(t("全画面を終了"))
        else:
            self._help_btn.show(); self._fs_btn.show()
            self._max_btn.setToolTip("")
            self._max_btn.setText("❐" if win.isMaximized() else "□")

    def is_caption_at(self, global_pt) -> bool:
        """全画面でないとき、タイトルバー上のボタン以外の領域なら True（OSがドラッグ可能=caption）。"""
        if self._overlay:
            return False
        local = self.mapFromGlobal(global_pt)
        if not self.rect().contains(local):
            return False
        for b in (self._help_btn, self._fs_btn, self._min_btn, self._max_btn, self._close_btn):
            if b.isVisible() and b.geometry().contains(local):
                return False
        return True

    def _toggle_fs(self):
        self.window().toggle_fullscreen()

    def _toggle_max(self):
        self.window().toggle_max()

    # ── 全画面時のオーバーレイ表示（マウスを最上部に寄せると現れる） ──
    def enter_overlay(self, win):
        """レイアウトから外し、ウィンドウ上部のオーバーレイにする（最初は隠す）。"""
        self._overlay = True; self._revealed = False
        self.setParent(win)
        self.setGeometry(0, -self.height(), win.width(), self.height())
        self.update_state_buttons()
        self.hide(); self.raise_()

    def exit_overlay(self, win):
        """レイアウト先頭へ戻して常時表示にする。"""
        self._overlay = False; self._revealed = False
        if self._slide_anim is not None:
            self._slide_anim.stop()
        self.setParent(None)
        win._central_layout.insertWidget(0, self)
        self.update_state_buttons()
        self.show()

    def reveal_overlay(self, win):
        if self._revealed: return
        self._revealed = True
        self.setGeometry(0, -self.height(), win.width(), self.height())
        self.show(); self.raise_()
        self._slide_to(0)

    def hide_overlay(self):
        if not self._overlay or not self._revealed: return
        self._revealed = False
        self._slide_to(-self.height(), then_hide=True)

    def _slide_to(self, y, then_hide=False):
        if self._slide_anim is not None:
            self._slide_anim.stop()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(140)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(self.x(), y))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if then_hide:
            anim.finished.connect(self.hide)
        self._slide_anim = anim
        anim.start()

    def mousePressEvent(self, e):
        # 通常はWM_NCHITTEST(HTCAPTION)でOSがドラッグ処理するが、念のためのフォールバック
        if e.button() == Qt.MouseButton.LeftButton \
                and not getattr(self.window(), "_fullscreen", False):
            self._drag_pos = e.globalPosition().toPoint() - self.window().geometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            win = self.window()
            if win.isMaximized():
                win.showNormal()
                self._drag_pos = QPoint(win.width() // 2, self.height() // 2)
            win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
