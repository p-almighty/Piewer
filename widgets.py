from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QHBoxLayout, QPushButton,
                               QDialog, QVBoxLayout, QTextBrowser, QGridLayout,
                               QScrollArea, QLineEdit, QCompleter, QLayout,
                               QInputDialog, QMessageBox, QCheckBox,
                               QTreeWidget, QTreeWidgetItem, QSlider, QComboBox,
                               QSpinBox, QDoubleSpinBox, QFileDialog,
                               QProgressBar, QPlainTextEdit, QProgressDialog)
from PySide6.QtCore import (Qt, Signal, QPoint, QRect, QSize, QTimer,
                            QPropertyAnimation, QEasingCurve,
                            QObject, QRunnable, QThreadPool)
from PySide6.QtGui import (QPixmap, QPainter, QColor, QFont, QKeySequence, QPainterPath,
                           QStandardItemModel, QStandardItem)
# 注: 配色・角丸の各値は theme.py に集約。以下のインラインQSSもその値に揃えている。

from config import APP_NAME, APP_VERSION, SHORTCUT_LABELS
import i18n
from i18n import t
import theme
import unicodedata
from pathlib import Path


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
      <tr><td style="color:#bfa6ff;">🎨 画質</td><td>画質補正・擬似カラー化（疑似色刷り）の設定</td></tr>
      <tr><td style="color:#bfa6ff;">「幅」ボタン</td><td>幅に合わせる（ホイールで縦スクロール）</td></tr>
      <tr><td style="color:#bfa6ff;">「縦読み」ボタン</td><td>縦スクロールの連続表示（Webtoon向け）</td></tr>
      <tr><td style="color:#bfa6ff;">マウス 戻る／進むボタン</td><td>本棚へ戻る／直前の本を再開</td></tr>
      <tr><td style="color:#bfa6ff;">⌨ ショートカット設定</td><td>下のボタンからキー割り当てを変更</td></tr>
    </table>
    <p style="color:#888;font-size:12px;">※ 右綴じ/見開き/幅/縦読みなどの表示設定は本ごとに記憶されます。</p>
    <h3 style="color:#b39dff;">📚 本棚</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">「＋ ファイル」</td><td>漫画を追加（ZIP/CBZ/EPUB/KEPUB/RAR/CBR/PDF）</td></tr>
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
      <tr><td style="color:#bfa6ff;">🎨 Image</td><td>Image correction &amp; pseudo-colorization settings</td></tr>
      <tr><td style="color:#bfa6ff;">“Width” button</td><td>Fit width (wheel scrolls vertically)</td></tr>
      <tr><td style="color:#bfa6ff;">“Vertical” button</td><td>Continuous vertical scroll (Webtoon)</td></tr>
      <tr><td style="color:#bfa6ff;">Mouse back / forward</td><td>Back to shelves / resume last book</td></tr>
      <tr><td style="color:#bfa6ff;">⌨ Shortcut settings</td><td>Change key bindings from the button below</td></tr>
    </table>
    <p style="color:#888;font-size:12px;">※ Display settings (R→L / spread / width / vertical) are remembered per book.</p>
    <h3 style="color:#b39dff;">📚 Shelves</h3>
    <table cellpadding="4">
      <tr><td style="color:#bfa6ff;">“+ File”</td><td>Add manga (ZIP/CBZ/EPUB/KEPUB/RAR/CBR/PDF)</td></tr>
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

    # ── 画質・着色 ──
    sub(t("🎨  画質・擬似カラー化"))

    def _fx_changed():
        rv = getattr(win, "reader_view", None)
        if rv is not None and win.stack.currentWidget() is rv:
            rv.apply_image_fx()
    action(t("🎨  画質補正・擬似カラー化"),
           t("白黒/カラーのページを見やすく補正し、お好みで“色刷り風”に着色します。"),
           lambda: ImageFxDialog(s, on_change=_fx_changed, parent=dlg).exec())
    action(t("🤖  AI着色"),
           t("プラグインで白黒ページを着色します。接続先（ローカル/クラウド）などの設定はこちら。"),
           lambda: AiColorConfigDialog(s, parent=dlg).exec())

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
           lambda: ReadingStatsDialog(win.library, s, dlg).exec())
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

    def __init__(self, current_tags, all_tags, parent=None, recent_tags=None):
        super().__init__(parent)
        self.setWindowTitle(t("タグを編集"))
        self.setMinimumWidth(480)
        self._selected = list(dict.fromkeys(str(t) for t in current_tags))
        self._chips: dict[str, QPushButton] = {}
        self._recent_chips: dict[str, QPushButton] = {}
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

        # 最近つけたタグ（上部に候補として表示。クリックでそのまま追加/解除）
        recent = list(dict.fromkeys(str(x).strip() for x in (recent_tags or []) if str(x).strip()))
        if recent:
            rlbl = QLabel(t("🕘 最近つけたタグ"))
            rlbl.setStyleSheet("color:#bfa6ff; font-size:12px; background:transparent;")
            lay.addWidget(rlbl)
            rhost = QWidget(); rhost.setStyleSheet("background:transparent;")
            rflow = FlowLayout(rhost, spacing=8)
            for tag in recent[:5]:
                rflow.addWidget(self._make_recent_chip(tag))
            lay.addWidget(rhost)

        # 既存タグ＋現在のタグをチップとして表示（折り返し）
        host = QWidget(); host.setStyleSheet("background:transparent;")
        self._flow = FlowLayout(host, spacing=8)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(host)
        scroll.setMinimumHeight(150)
        self._scroll = scroll
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

    def _make_recent_chip(self, tag: str) -> QPushButton:
        b = QPushButton(tag); b.setCheckable(True); b.setChecked(tag in self._selected)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setStyleSheet(self.CHIP_QSS)
        b.toggled.connect(lambda on, t=tag: self._on_recent_toggle(t, on))
        self._recent_chips[tag] = b
        return b

    def _on_recent_toggle(self, tag: str, on: bool):
        # 候補チップの操作を本体チップ（＝選択状態の正）へ反映
        main = self._add_chip(tag)
        if main is not None and main.isChecked() != on:
            main.setChecked(on)

    def _on_toggle(self, tag: str, on: bool):
        if on and tag not in self._selected:
            self._selected.append(tag)
        elif not on and tag in self._selected:
            self._selected.remove(tag)
        # 同じタグの候補チップがあれば表示を同期（シグナルの往復を防ぐ）
        rb = self._recent_chips.get(tag)
        if rb is not None and rb.isChecked() != on:
            rb.blockSignals(True); rb.setChecked(on); rb.blockSignals(False)

    def _match_existing(self, text: str) -> str | None:
        """入力テキストと一致する既存タグ（大小文字・前後空白を無視）を返す。"""
        low = text.strip().casefold()
        for tag in self._chips:
            if tag.casefold() == low:
                return tag
        return None

    def _add_new(self):
        text = self._new_edit.text().strip()
        if not text:
            return
        self._new_edit.clear()
        # 既存タグと一致すれば新規作成せず、その既存タグを選択する
        tag = self._match_existing(text) or text
        b = self._add_chip(tag)
        if b is not None:
            if not b.isChecked():
                b.setChecked(True)   # toggled シグナルで _selected に追加される
            self._scroll.ensureWidgetVisible(b)   # 選択した既存タグを見える位置へ

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

    def __init__(self, library, settings=None, parent=None):
        super().__init__(parent)
        self.library = library
        self.settings = settings
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
        auto_row.addWidget(auto_btn)
        if self.settings is not None:
            cat_btn = QPushButton(t("✏ 分類名を編集"))
            cat_btn.setToolTip(t("作者・サークル・原作などの分類名を自分の命名に合わせて変更します。"))
            cat_btn.clicked.connect(self._edit_labels)
            auto_row.addWidget(cat_btn)
        auto_row.addStretch()
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
        AutoTagDialog(self.library, self.settings, self).exec()
        self._build()   # 追加されたタグを一覧へ反映

    def _edit_labels(self):
        if self.settings is None:
            return
        if CategoryLabelsDialog(self.library, self.settings, self).exec():
            self._build()   # 接頭辞を置換した場合に一覧へ反映

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
    """ファイル名の構造から自動タグ付け。プレビューしてから一括適用する。"""

    def __init__(self, library, settings=None, parent=None):
        super().__init__(parent)
        self.library = library
        self.settings = settings
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
        # 現在の分類名（ユーザー設定を反映）
        if settings is not None and hasattr(settings, "effective_tag_labels"):
            self._labels = settings.effective_tag_labels()
        else:
            import auto_tag
            self._labels = dict(auto_tag.DEFAULT_LABELS)
        lb = self._labels

        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        lay.addWidget(QLabel(t("ファイル名から {a}・{c}・{p}・{e} 等を抽出してタグを付けます。\n"
                               "既存のタグは消さず追加するだけです。").format(
                               a=lb["author"], c=lb["circle"], p=lb["parody"], e=lb["event"])))
        note = QLabel(t("※ 実験的機能です。ファイル名の付け方によっては誤って抽出することがあります。"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#ffc107;font-size:12px;background:transparent;")
        lay.addWidget(note)

        # 仕様の表示トグル＋分類名の編集
        tool_row = QHBoxLayout(); tool_row.setSpacing(6)
        self._spec_btn = QPushButton(t("ⓘ 命名ルールを表示"))
        self._spec_btn.clicked.connect(self._toggle_spec)
        tool_row.addWidget(self._spec_btn)
        if settings is not None:
            edit_btn = QPushButton(t("✏ 分類名を編集"))
            edit_btn.clicked.connect(self._edit_labels)
            tool_row.addWidget(edit_btn)
        tool_row.addStretch()
        lay.addLayout(tool_row)

        import auto_tag
        self._spec = QLabel(auto_tag.spec_text(self._labels, i18n.get_lang()))
        self._spec.setWordWrap(True); self._spec.setVisible(False)
        self._spec.setStyleSheet("color:#bbb;font-size:12px;background:#1f1a29;"
                                 "border:1px solid #393350;border-radius:10px;padding:10px 12px;")
        lay.addWidget(self._spec)

        # 抽出する種類
        cb_row = QHBoxLayout(); cb_row.setSpacing(14)
        self._cb_artist = QCheckBox(t("{a}・{c}").format(a=lb["author"], c=lb["circle"]))
        self._cb_artist.setChecked(True)
        self._cb_parody = QCheckBox(lb["parody"]); self._cb_parody.setChecked(True)
        self._cb_event = QCheckBox(t("{e}・その他").format(e=lb["event"])); self._cb_event.setChecked(True)
        self._cb_folder = QCheckBox(t("親フォルダ名")); self._cb_folder.setChecked(False)
        self._cb_prefix = QCheckBox(t("接頭辞をつける（{a}: など）").format(a=lb["author"]))
        self._cb_prefix.setChecked(True)
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

    def _toggle_spec(self):
        show = not self._spec.isVisible()
        self._spec.setVisible(show)
        self._spec_btn.setText(t("ⓘ 命名ルールを隠す") if show else t("ⓘ 命名ルールを表示"))

    def _edit_labels(self):
        if self.settings is None:
            return
        if CategoryLabelsDialog(self.library, self.settings, self).exec():
            self.accept()   # ラベルが変わったので開き直してもらう（再構築が単純）

    def _recompute(self):
        import auto_tag
        books = [b for shelf in self.library.shelves for b in shelf["books"]]
        self._mapping, counts = auto_tag.propose(
            books, self._types(), self._cb_prefix.isChecked(), self._labels)
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


class CategoryLabelsDialog(QDialog):
    """オートタグの分類名（作者/サークル/原作/イベント/フォルダ）を自由にリネームする。

    変更後は新しい分類名で自動タグ付け・絞り込みのグループ化が行われる。
    既存タグの接頭辞も合わせて置き換えるか選べる。
    """
    # (役割キー, 説明)
    _ROLES = (
        ("author", "作者　— [サークル (作者)] の作者部分"),
        ("circle", "サークル　— [サークル] / [サークル (作者)]"),
        ("parody", "原作・作品名　— タイトル後の (…)"),
        ("event",  "イベント　— 先頭の (…)"),
        ("folder", "フォルダ　— 親フォルダ名"),
    )

    def __init__(self, library, settings, parent=None):
        super().__init__(parent)
        self.library = library
        self.settings = settings
        self._old = settings.effective_tag_labels()
        self.setWindowTitle(t("分類名の編集"))
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QLineEdit { background:#2b2539; color:#ddd; border:1px solid #463d63;
                        border-radius:10px; padding:6px 10px; font-size:13px; }
            QLineEdit:focus { border-color:#a06cff; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:6px 14px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#save { background:#a06cff; color:white; border:none; padding:8px 24px; }
            QPushButton#save:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(10)
        intro = QLabel(t("ファイル名から抽出した要素につける分類名（接頭辞）を変更できます。\n"
                         "自分のファイル命名に合わせて自由に名前を付けてください。"))
        intro.setWordWrap(True); lay.addWidget(intro)

        self._edits = {}
        import auto_tag
        for role, desc in self._ROLES:
            r = QHBoxLayout(); r.setSpacing(8)
            lbl = QLabel(t(desc)); lbl.setMinimumWidth(230); lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#bbb;font-size:12px;background:transparent;")
            ed = QLineEdit(self._old.get(role, auto_tag.DEFAULT_LABELS[role]))
            ed.setPlaceholderText(auto_tag.DEFAULT_LABELS[role])
            self._edits[role] = ed
            r.addWidget(lbl, 1); r.addWidget(ed, 1)
            lay.addLayout(r)

        hint = QLabel(t("※ 「:」は使えません。空欄にすると既定名に戻ります。"))
        hint.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        hint.setWordWrap(True); lay.addWidget(hint)

        row = QHBoxLayout()
        reset = QPushButton(t("既定に戻す")); reset.clicked.connect(self._reset)
        row.addWidget(reset); row.addStretch()
        cancel = QPushButton(t("キャンセル")); cancel.clicked.connect(self.reject)
        save = QPushButton(t("保存")); save.setObjectName("save"); save.clicked.connect(self._save)
        row.addWidget(cancel); row.addWidget(save)
        lay.addLayout(row)

    def _reset(self):
        import auto_tag
        for role, ed in self._edits.items():
            ed.setText(auto_tag.DEFAULT_LABELS[role])

    def _save(self):
        import auto_tag
        new = {}
        for role, ed in self._edits.items():
            v = ed.text().strip()
            if ":" in v or "：" in v:
                QMessageBox.warning(self, t("入力エラー"),
                                    t("分類名に「:」は使えません。"))
                return
            new[role] = v or auto_tag.DEFAULT_LABELS[role]
        # 分類名どうしの重複を禁止（グループが混ざるため）
        vals = list(new.values())
        if len(set(vals)) != len(vals):
            QMessageBox.warning(self, t("入力エラー"),
                                t("分類名が重複しています。別々の名前にしてください。"))
            return
        self.settings.set_tag_labels(new)

        # 変わった分類名があれば、既存タグの接頭辞も置き換えるか確認
        changed = [(role, self._old[role], new[role])
                   for role in new if self._old.get(role) != new[role]]
        migrated = 0
        if changed:
            ans = QMessageBox.question(
                self, t("既存タグの置き換え"),
                t("既存の本に付いているタグの分類名も新しい名前に置き換えますか？\n"
                  "（例: 「作者:〇〇」→「{ex}:〇〇」）").format(ex=changed[0][2]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                for _role, old_pfx, new_pfx in changed:
                    migrated += self.library.rename_tag_prefix(old_pfx, new_pfx)
        if migrated:
            QMessageBox.information(self, t("完了"),
                                   t("{n} 冊のタグを更新しました。").format(n=migrated))
        self.accept()


class ImageFxDialog(QDialog):
    """画質補正＋擬似カラー化（疑似色刷り）の設定。変更は即プレビュー反映する。"""

    def __init__(self, settings, on_change=None, parent=None, reader=None):
        super().__init__(parent)
        import image_fx
        self.settings = settings
        self._on_change = on_change
        self._reader = reader
        self._cfg = image_fx.merge(getattr(settings, "image_fx", {}) or {})
        self.setWindowTitle(t("🎨 画質・擬似カラー化"))
        self.setMinimumWidth(430)
        self.setStyleSheet("""
            QDialog { background:#262032; }
            QLabel { color:#ddd; font-size:13px; background:transparent; }
            QCheckBox { color:#ddd; font-size:13px; background:transparent; }
            QComboBox { background:#2b2539; color:#ddd; border:1px solid #463d63;
                        border-radius:10px; padding:5px 10px; font-size:13px; }
            QComboBox QAbstractItemView { background:#2b2539; color:#ddd;
                        selection-background-color:#a06cff; }
            QSlider::groove:horizontal { height:6px; background:#3a3350; border-radius:3px; }
            QSlider::handle:horizontal { width:16px; margin:-6px 0; border-radius:8px; background:#a06cff; }
            QSlider::sub-page:horizontal { background:#a06cff; border-radius:3px; }
            QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                          border-radius:10px; padding:6px 14px; font-size:12px; }
            QPushButton:hover { background:#423a5a; }
            QPushButton#close { background:#a06cff; color:white; border:none; padding:7px 24px; }
            QPushButton#close:hover { background:#b488ff; }
        """)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(9)

        def sub(text):
            s = QLabel(text)
            s.setStyleSheet("color:#bfa6ff;font-size:12px;font-weight:bold;background:transparent;")
            lay.addSpacing(2); lay.addWidget(s)

        self._on_cb = QCheckBox(t("画質補正・擬似カラー化を有効にする"))
        self._on_cb.setChecked(bool(self._cfg["on"]))
        self._on_cb.stateChanged.connect(self._changed)
        lay.addWidget(self._on_cb)
        note = QLabel(t("白黒/カラーのページを見やすく補正し、お好みで“色刷り風”に着色します。"))
        note.setWordWrap(True); note.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(note)

        # ① 画質補正
        sub(t("画質補正"))
        self._auto_cb = QCheckBox(t("自動レベル補正（白を白く・黒を黒く）"))
        self._auto_cb.setChecked(bool(self._cfg["autolevel"]))
        self._auto_cb.stateChanged.connect(self._changed)
        lay.addWidget(self._auto_cb)

        g_row = QHBoxLayout(); g_row.setSpacing(8)
        g_row.addWidget(QLabel(t("明るさ(ガンマ)")))
        self._gamma = QSlider(Qt.Orientation.Horizontal); self._gamma.setRange(50, 200)
        self._gamma.setValue(int(round(float(self._cfg["gamma"]) * 100)))
        self._gamma.valueChanged.connect(self._changed)
        self._gamma_lbl = QLabel(""); self._gamma_lbl.setMinimumWidth(42)
        g_row.addWidget(self._gamma, 1); g_row.addWidget(self._gamma_lbl)
        lay.addLayout(g_row)

        self._sharp_cb = QCheckBox(t("シャープ（くっきりさせる）"))
        self._sharp_cb.setChecked(bool(self._cfg["sharpen"]))
        self._sharp_cb.stateChanged.connect(self._changed)
        lay.addWidget(self._sharp_cb)

        # ② 擬似カラー化
        sub(t("擬似カラー化（疑似色刷り）"))
        c_row = QHBoxLayout(); c_row.setSpacing(8)
        c_row.addWidget(QLabel(t("色")))
        self._color = QComboBox()
        for key, name in image_fx.COLOR_ORDER:
            self._color.addItem(t(name), key)
        idx = self._color.findData(self._cfg["color"])
        self._color.setCurrentIndex(idx if idx >= 0 else 0)
        self._color.currentIndexChanged.connect(self._changed)
        c_row.addWidget(self._color, 1)
        lay.addLayout(c_row)

        s_row = QHBoxLayout(); s_row.setSpacing(8)
        s_row.addWidget(QLabel(t("強さ")))
        self._strength = QSlider(Qt.Orientation.Horizontal); self._strength.setRange(0, 100)
        self._strength.setValue(int(self._cfg["strength"]))
        self._strength.valueChanged.connect(self._changed)
        self._strength_lbl = QLabel(""); self._strength_lbl.setMinimumWidth(42)
        s_row.addWidget(self._strength, 1); s_row.addWidget(self._strength_lbl)
        lay.addLayout(s_row)

        hint = QLabel(t("※ 擬似カラー化は“色がついた風”にする処理で、実際の色を再現するものではありません。"))
        hint.setWordWrap(True); hint.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        lay.addWidget(hint)

        # ③ AI超解像（別ダイアログで設定。低解像度ページの高精細化）
        sub(t("AI超解像（高解像度化）"))
        urow = QHBoxLayout(); urow.setSpacing(8)
        self._up_open_btn = QPushButton(t("🔍 AI超解像の設定を開く…"))
        self._up_open_btn.clicked.connect(self._open_upscale)
        urow.addWidget(self._up_open_btn)
        self._up_state_lbl = QLabel("")
        self._up_state_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        urow.addWidget(self._up_state_lbl, 1)
        lay.addLayout(urow)
        self._refresh_upscale_state()

        row = QHBoxLayout()
        reset = QPushButton(t("既定に戻す")); reset.clicked.connect(self._reset)
        row.addWidget(reset); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close"); close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)

        self._refresh_labels(); self._apply_enabled_state()

    def _open_upscale(self, *_):
        import ai_upscale
        on_change = self._reader.apply_ai_upscale if self._reader is not None else None
        AiUpscaleDialog(self.settings, on_change=on_change,
                        reader=self._reader, parent=self).exec()
        self._refresh_upscale_state()

    def _refresh_upscale_state(self):
        import ai_upscale
        on = ai_upscale.active(getattr(self.settings, "ai_upscale", {}) or {})
        if on:
            self._up_state_lbl.setText(t("有効"))
            self._up_state_lbl.setStyleSheet("color:#7fd6a0;font-size:11px;background:transparent;")
        else:
            self._up_state_lbl.setText(t("無効"))
            self._up_state_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")

    def _reset(self):
        import image_fx
        d = image_fx.DEFAULT
        self._on_cb.setChecked(d["on"]); self._auto_cb.setChecked(d["autolevel"])
        self._gamma.setValue(int(round(d["gamma"] * 100))); self._sharp_cb.setChecked(d["sharpen"])
        i = self._color.findData(d["color"]); self._color.setCurrentIndex(i if i >= 0 else 0)
        self._strength.setValue(int(d["strength"]))
        self._changed()

    def _refresh_labels(self):
        self._gamma_lbl.setText(f"{self._gamma.value() / 100.0:.2f}")
        self._strength_lbl.setText(f"{self._strength.value()}%")

    def _apply_enabled_state(self):
        en = self._on_cb.isChecked()
        for w in (self._auto_cb, self._gamma, self._sharp_cb, self._color, self._strength):
            w.setEnabled(en)

    def _changed(self, *_):
        self._cfg = {
            "on": self._on_cb.isChecked(),
            "autolevel": self._auto_cb.isChecked(),
            "gamma": self._gamma.value() / 100.0,
            "sharpen": self._sharp_cb.isChecked(),
            "color": self._color.currentData() or "none",
            "strength": self._strength.value(),
        }
        self._refresh_labels(); self._apply_enabled_state()
        self.settings.image_fx = dict(self._cfg)
        self.settings.save()
        if self._on_change:
            self._on_change()


class _ColorTestSignals(QObject):
    done = Signal(bool, str)   # (成功か, メッセージ)


class _ColorTestWorker(QRunnable):
    """設定した着色プラグインに小さなテスト画像を送り、繋がるか確認する（UIを止めない）。"""

    def __init__(self, provider, opts: dict):
        super().__init__()
        self.provider = provider; self.opts = opts
        self.signals = _ColorTestSignals()

    def run(self):
        try:
            from PIL import Image
            # 64x96 のグレーのグラデーション（白黒ページの代わり）
            test = Image.new("L", (64, 96))
            px = test.load()
            for y in range(96):
                for x in range(64):
                    px[x, y] = int((x / 63) * 255)
            out = self.provider.colorize(test.convert("RGB"), dict(self.opts))
            if out is None:
                self.signals.done.emit(False, t("着色結果が空でした。"))
            else:
                self.signals.done.emit(True, t("接続成功。着色サーバから画像を受け取れました。"))
        except Exception as e:
            self.signals.done.emit(False, str(e))


class _UpscaleTestWorker(QRunnable):
    """設定した超解像プラグインに小さなテスト画像を送り、繋がるか確認する（UIを止めない）。"""

    def __init__(self, provider, opts: dict):
        super().__init__()
        self.provider = provider; self.opts = opts
        self.signals = _ColorTestSignals()   # done(ok, msg) を流用

    def run(self):
        try:
            from PIL import Image
            test = Image.new("RGB", (48, 64), (200, 200, 200))
            out = self.provider.upscale(test, dict(self.opts))
            if out is None:
                self.signals.done.emit(False, t("結果が空でした。"))
            elif out.size[0] <= test.size[0]:
                self.signals.done.emit(True, t("接続成功（ただし拡大されていません。サーバの拡大率を確認）。"))
            else:
                self.signals.done.emit(True, t("接続成功。超解像サーバから拡大画像を受け取れました。"))
        except Exception as e:
            self.signals.done.emit(False, str(e))


class _CuganPrepWorker(QRunnable):
    """Real-CUGAN の推論コード＋指定(scale,denoise)の重みをDLする（UIを止めない）。

    torch/python は着色の構築分を流用する前提（深い依存は再導入しない）。
    """

    def __init__(self, scale: int, denoise: int):
        super().__init__()
        self.scale = scale; self.denoise = denoise
        self.signals = _ColorTestSignals()   # done(ok, msg) を流用

    def run(self):
        try:
            import ai_runtime
            ai_runtime.download_cugan_repo()
            ai_runtime.download_cugan_weight(self.scale, self.denoise)
            self.signals.done.emit(True, t("Real-CUGAN の準備が完了しました。"))
        except Exception as e:
            self.signals.done.emit(False, str(e))


_AI_QSS = """
    QDialog { background:#262032; }
    QLabel { color:#ddd; font-size:13px; background:transparent; }
    QCheckBox { color:#ddd; font-size:13px; background:transparent; }
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background:#2b2539; color:#ddd;
                border:1px solid #463d63; border-radius:10px; padding:5px 10px; font-size:13px; }
    QComboBox QAbstractItemView { background:#2b2539; color:#ddd;
                selection-background-color:#a06cff; }
    QPushButton { background:#322b45; color:#ddd; border:1px solid #463d63;
                  border-radius:10px; padding:6px 14px; font-size:12px; }
    QPushButton:hover { background:#423a5a; }
    QPushButton#close { background:#a06cff; color:white; border:none; padding:7px 24px; }
    QPushButton#close:hover { background:#b488ff; }
"""


class _AiCacheMixin:
    """着色データ（ディスクキャッシュ）の容量表示＋全削除（両ダイアログ共通）。"""

    def _build_cache_row(self, lay):
        crow = QHBoxLayout(); crow.setSpacing(8)
        self._cache_lbl = QLabel("")
        self._cache_lbl.setStyleSheet("color:#bfa6ff;font-size:12px;background:transparent;")
        crow.addWidget(self._cache_lbl, 1)
        btn = QPushButton(t("着色データを削除")); btn.clicked.connect(self._clear_cache_clicked)
        crow.addWidget(btn); lay.addLayout(crow)
        self._update_cache_label()

    def _update_cache_label(self):
        import ai_color
        mb = ai_color.cache_size_bytes() / (1024 * 1024)
        self._cache_lbl.setText(t("着色データ: {mb:.1f} MB").format(mb=mb))

    def _clear_cache_clicked(self, *_):
        import ai_color
        if ai_color.cache_size_bytes() <= 0:
            self._cache_lbl.setText(t("着色データ: 0.0 MB（削除するものはありません）"))
            return
        if QMessageBox.question(self, t("着色データの削除"),
                                t("保存済みの着色データを全て削除しますか？\n"
                                  "（次に開いたページから再着色されます）"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) != QMessageBox.StandardButton.Yes:
            return
        ai_color.clear_cache()
        self._update_cache_label()
        r = getattr(self, "_reader", None)
        if r is not None:
            r.apply_ai_color()   # 表示中のキャッシュも破棄→再描画/再着色


class _MoveWorker(QObject):
    """保存先の移動をバックグラウンドで行うワーカー（進捗をsignalで通知）。"""

    progress = Signal(int)     # 0..100
    finished = Signal(bool)    # 成否

    def __init__(self, new_base):
        super().__init__()
        self._new = new_base
        self._cancel = False
        self._last = -1

    def cancel(self):
        self._cancel = True

    def run(self):
        import ai_runtime

        def pcb(done, total):
            pct = int(done * 100 / total) if total else 0
            if pct != self._last:
                self._last = pct
                self.progress.emit(pct)

        try:
            ok = ai_runtime.move_base_dir_progress(self._new, pcb, lambda: self._cancel)
        except Exception:
            ok = False
        self.finished.emit(ok)


class AiRuntimeSetupDialog(QDialog):
    """AI着色ランタイムの自動構築ウィザード（フェーズB）。

    standalone Python → torch等 → 着色プログラム → 重み を `~/.manga_viewer/ai_runtime/`
    に自動で用意する。完了するとサーバ設定（python/repo/device）を自動入力する。
    重みの自動DLが失敗したときは、ブラウザでリンクを開いて手動で配置できる。
    """

    def __init__(self, settings, on_done=None, parent=None):
        super().__init__(parent)
        import ai_runtime
        import ai_server
        import ai_color
        self.settings = settings
        self._on_done = on_done
        self._builder = None
        self._rows: dict = {}
        # 保存先を設定から復元（既定は ~/.manga_viewer/ai_runtime）
        _sv0 = ai_color.merge(getattr(settings, "ai_color", {}) or {})["server"]
        ai_runtime.set_base_dir(_sv0.get("runtime_dir") or "")
        self.setWindowTitle(t("🤖 AI着色を自動で準備"))
        self.setMinimumWidth(540)
        self.setStyleSheet(_AI_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(9)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(self._note)

        warn = QLabel(t("※ ダウンロード量が大きく（GPU版は約2.5GB／CPU版は約300MB）、回線により"
                        "数分〜十数分かかります。GPUを使うには NVIDIA ドライバが必要です。"))
        warn.setWordWrap(True); warn.setStyleSheet("color:#c8a24a;font-size:11px;background:transparent;")
        lay.addWidget(warn)

        # 保存先
        lrow = QHBoxLayout(); lrow.setSpacing(8)
        llb = QLabel(t("保存先")); llb.setMinimumWidth(60); lrow.addWidget(llb)
        self._loc_edit = QLineEdit(); self._loc_edit.setReadOnly(True)
        lrow.addWidget(self._loc_edit, 1)
        locb = QPushButton(t("変更")); locb.clicked.connect(self._change_location)
        lrow.addWidget(locb); lay.addLayout(lrow)
        self._update_location_labels()

        # 処理（GPU/CPU）
        drow = QHBoxLayout(); drow.setSpacing(8)
        drow.addWidget(QLabel(t("処理")))
        self._dev_cb = QComboBox()
        self._dev_cb.addItem(t("GPU (CUDA・速い)"), "cuda")
        self._dev_cb.addItem(t("CPU（遅い・GPU無しでも可）"), "cpu")
        raw = getattr(settings, "ai_color", {}) or {}
        raw_sv = raw.get("server") if isinstance(raw.get("server"), dict) else {}
        dev = raw_sv.get("device") or ("cuda" if ai_server.has_nvidia_gpu() else "cpu")
        di = self._dev_cb.findData(dev); self._dev_cb.setCurrentIndex(di if di >= 0 else 0)
        drow.addWidget(self._dev_cb, 1); lay.addLayout(drow)

        # ステップ一覧
        steps_box = QVBoxLayout(); steps_box.setSpacing(3)
        for key, label in ai_runtime.STEPS:
            row = QHBoxLayout(); row.setSpacing(8)
            dot = QLabel("○"); dot.setFixedWidth(18)
            dot.setStyleSheet("color:#6f6690;font-size:14px;background:transparent;")
            name = QLabel(t(label)); name.setMinimumWidth(170)
            name.setStyleSheet("color:#ddd;font-size:12px;background:transparent;")
            st = QLabel(""); st.setWordWrap(True)
            st.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
            row.addWidget(dot); row.addWidget(name); row.addWidget(st, 1)
            steps_box.addLayout(row)
            self._rows[key] = (dot, st)
        lay.addLayout(steps_box)

        self._bar = QProgressBar(); self._bar.setRange(0, 100); self._bar.setValue(0)
        self._bar.setTextVisible(False); self._bar.setFixedHeight(8)
        lay.addWidget(self._bar)

        self._log = QPlainTextEdit(); self._log.setReadOnly(True)
        self._log.setFixedHeight(110)
        self._log.setStyleSheet("background:#1e1930;color:#9a8fb8;font-size:10px;"
                                "border:1px solid #463d63;border-radius:8px;")
        lay.addWidget(self._log)

        # ボタン列
        brow = QHBoxLayout(); brow.setSpacing(8)
        self._manual_btn = QPushButton(t("重みを手動で配置"))
        self._manual_btn.clicked.connect(self._manual_weights)
        brow.addWidget(self._manual_btn)
        brow.addStretch()
        self._start_btn = QPushButton(t("構築開始")); self._start_btn.setObjectName("close")
        self._start_btn.clicked.connect(self._start)
        brow.addWidget(self._start_btn)
        self._close_btn = QPushButton(t("閉じる")); self._close_btn.clicked.connect(self.reject)
        brow.addWidget(self._close_btn)
        lay.addLayout(brow)

        self._refresh_status()

    # ── 保存先 ──────────────────────────────────────────────

    def _update_location_labels(self):
        import ai_runtime
        base = str(ai_runtime.base_dir())
        self._loc_edit.setText(base)
        self._loc_edit.setToolTip(base)
        self._note.setText(t("AI着色に必要な一式（実行用Python・AIライブラリ・着色プログラム・モデル）を"
                             "自動でダウンロードして下記の保存先に用意します。"))

    def _change_location(self, *_):
        import ai_runtime
        if self._builder is not None and self._builder.is_running():
            return
        d = QFileDialog.getExistingDirectory(self, t("保存先フォルダを選択（この中に専用フォルダを作成）"))
        if not d:
            return
        new_base = str(Path(d) / ai_runtime.SUBDIR_NAME)
        old_base = str(ai_runtime.base_dir())
        if Path(new_base).resolve() == Path(old_base).resolve():
            return
        # 既に構築済みのものがあれば「移動」を提案
        moved = False
        any_built = any(ai_runtime.status(self._dev_cb.currentData() or "cpu").values())
        if any_built and ai_runtime.base_dir().exists():
            ans = QMessageBox.question(
                self, t("保存先の変更"),
                t("構築済みのファイルを新しい保存先へ移動しますか？\n"
                  "「いいえ」を選ぶと、新しい保存先で最初から構築し直します。\n\n"
                  "移動先: {dst}").format(dst=new_base),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                return
            if ans == QMessageBox.StandardButton.Yes:
                ok = self._move_with_progress(new_base)
                if not ok:
                    return   # 失敗/中止時の案内は _move_with_progress 内で実施
                moved = True
        if not moved:
            ai_runtime.set_base_dir(new_base)
        self._persist_location()
        self._update_location_labels()
        self._refresh_status()

    def _move_with_progress(self, new_base) -> bool:
        """構築済みファイルの移動を別スレッドで実行し、進捗ダイアログを表示する。"""
        import threading
        nb = Path(new_base)
        if nb.exists() and any(nb.iterdir()):
            QMessageBox.warning(self, t("保存先の変更"),
                                t("移動先が既に使われています。別のフォルダを選んでください。"))
            return False
        dlg = QProgressDialog(t("構築済みファイルを新しい保存先へ移動しています…"),
                              t("中止"), 0, 100, self)
        dlg.setWindowTitle(t("保存先の変更"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setAutoClose(False); dlg.setAutoReset(False); dlg.setMinimumDuration(0)
        dlg.setValue(0)
        worker = _MoveWorker(new_base)
        self._move_worker = worker   # GC防止
        state = {"ok": False}
        worker.progress.connect(dlg.setValue)

        def _fin(ok):
            state["ok"] = ok
            dlg.reset()
        worker.finished.connect(_fin)
        dlg.canceled.connect(worker.cancel)
        th = threading.Thread(target=worker.run, daemon=True)
        th.start()
        dlg.exec()
        th.join(5)
        if not state["ok"]:
            QMessageBox.warning(
                self, t("保存先の変更"),
                t("移動できませんでした（中止された、または移動先が使用中の可能性があります）。"))
        return state["ok"]

    def _persist_location(self):
        """保存先と（構築済みなら）派生パスを設定へ書き込む。"""
        import ai_color
        import ai_runtime
        cur = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})
        sv = cur["server"]
        sv["runtime_dir"] = str(ai_runtime.base_dir())
        if ai_runtime.is_ready():
            sv["python"] = str(ai_runtime.runtime_python_exe())
            sv["repo"] = str(ai_runtime.runtime_repo_dir())
        cur["server"] = sv
        self.settings.ai_color = dict(cur)
        self.settings.save()

    # ── 状態表示 ────────────────────────────────────────────

    def _refresh_status(self):
        import ai_runtime
        dev = self._dev_cb.currentData() or "cpu"
        stt = ai_runtime.status(dev)
        for key, (dot, lbl) in self._rows.items():
            done = stt.get(key, False)
            dot.setText("●" if done else "○")
            dot.setStyleSheet(("color:#7fd6a0" if done else "color:#6f6690")
                              + ";font-size:14px;background:transparent;")
            if done and not lbl.text():
                lbl.setText(t("導入済み"))
        if ai_runtime.is_ready(dev):
            self._start_btn.setText(t("再構築"))

    def _set_step(self, key: str, status: str, msg: str):
        if key not in self._rows:
            return
        dot, lbl = self._rows[key]
        sym = {"running": "◐", "done": "●", "skipped": "●", "error": "✕"}.get(status, "○")
        col = {"running": "#bfa6ff", "done": "#7fd6a0", "skipped": "#7fd6a0",
               "error": "#e08a7f"}.get(status, "#6f6690")
        dot.setText(sym)
        dot.setStyleSheet(f"color:{col};font-size:14px;background:transparent;")
        lbl.setStyleSheet(f"color:{col};font-size:11px;background:transparent;")
        lbl.setText(msg)

    # ── 構築 ────────────────────────────────────────────────

    def _start(self, *_):
        import ai_runtime
        if self._builder is not None and self._builder.is_running():
            return
        dev = self._dev_cb.currentData() or "cpu"
        self._log.clear()
        self._bar.setRange(0, 0)   # 不定（開始直後）
        self._dev_cb.setEnabled(False)
        self._start_btn.setEnabled(False)
        self._manual_btn.setEnabled(False)
        self._close_btn.setText(t("中止"))
        self._builder = ai_runtime.RuntimeBuilder(self)
        self._builder.step_status.connect(self._set_step)
        self._builder.progress.connect(self._on_progress)
        self._builder.log.connect(self._on_log)
        self._builder.finished.connect(self._on_finished)
        self._builder.start(device=dev)

    def _on_progress(self, pct: int):
        if pct < 0:
            self._bar.setRange(0, 0)   # 不定
        else:
            self._bar.setRange(0, 100); self._bar.setValue(pct)

    def _on_log(self, line: str):
        self._log.appendPlainText(line)

    def _on_finished(self, ok: bool, msg: str):
        self._bar.setRange(0, 100); self._bar.setValue(100 if ok else 0)
        self._dev_cb.setEnabled(True)
        self._start_btn.setEnabled(True)
        self._manual_btn.setEnabled(True)
        self._close_btn.setText(t("閉じる"))
        self._refresh_status()
        if ok:
            self._persist_runtime()
            QMessageBox.information(self, t("AI着色の準備"), t(msg))
            if self._on_done:
                self._on_done()
            self.accept()
        else:
            QMessageBox.warning(self, t("AI着色の準備"), t(msg))

    def _persist_runtime(self):
        """構築できたランタイムをサーバ設定に書き込む（自動起動ONにする）。"""
        import ai_color
        import ai_runtime
        cur = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})
        sv = cur["server"]
        sv["manage"] = True
        sv["python"] = str(ai_runtime.runtime_python_exe())
        sv["repo"] = str(ai_runtime.runtime_repo_dir())
        sv["device"] = self._dev_cb.currentData() or "cpu"
        sv["runtime_dir"] = str(ai_runtime.base_dir())
        cur["server"] = sv
        cur["opts"] = {**cur.get("opts", {}),
                       "endpoint": f"http://127.0.0.1:{sv['port']}/colorize"}
        self.settings.ai_color = dict(cur)
        self.settings.save()

    # ── 重みの手動フォールバック ────────────────────────────

    def _manual_weights(self, *_):
        import ai_runtime
        if not ai_runtime.repo_ready():
            QMessageBox.information(
                self, t("重みを手動で配置"),
                t("先に「構築開始」で着色プログラムまで用意してください。"))
            return
        dlg = _ManualWeightsDialog(self)
        dlg.exec()
        self._refresh_status()

    def closeEvent(self, e):
        if self._builder is not None and self._builder.is_running():
            if QMessageBox.question(
                    self, t("構築の中止"),
                    t("構築を中止しますか？（途中までの内容は保存され、次回は続きから再開できます）"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    ) != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self._builder.cancel()
        super().closeEvent(e)

    def reject(self):
        if self._builder is not None and self._builder.is_running():
            self.close()   # closeEvent の確認に回す
            return
        super().reject()


class _ManualWeightsDialog(QDialog):
    """重み（モデルファイル）をブラウザでDLして手動配置するための補助ダイアログ。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        import ai_runtime
        self.setWindowTitle(t("重みを手動で配置"))
        self.setMinimumWidth(520)
        self.setStyleSheet(_AI_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(9)

        note = QLabel(t("自動DLが失敗する場合は、各ファイルを「リンクを開く」でブラウザから"
                        "ダウンロードし、「ファイルを選択」で取り込んでください。"))
        note.setWordWrap(True); note.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(note)

        self._labels = []
        for i, (fid, rel, label) in enumerate(ai_runtime.WEIGHTS):
            box = QVBoxLayout(); box.setSpacing(4)
            head = QLabel(t(label)); head.setStyleSheet(
                "color:#bfa6ff;font-size:12px;font-weight:bold;background:transparent;")
            box.addWidget(head)
            row = QHBoxLayout(); row.setSpacing(8)
            openb = QPushButton(t("リンクを開く"))
            openb.clicked.connect(lambda _=False, f=fid: self._open(ai_runtime.gdrive_url(f)))
            pickb = QPushButton(t("ファイルを選択"))
            pickb.clicked.connect(lambda _=False, idx=i: self._pick(idx))
            stat = QLabel(""); stat.setStyleSheet(
                "color:#8a7fa6;font-size:11px;background:transparent;")
            row.addWidget(openb); row.addWidget(pickb); row.addWidget(stat, 1)
            box.addLayout(row); lay.addLayout(box)
            self._labels.append(stat)
        self._refresh()

        r = QHBoxLayout(); r.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close"); close.clicked.connect(self.accept)
        r.addWidget(close); lay.addLayout(r)

    def _refresh(self):
        import ai_runtime
        for i, (fid, rel, label) in enumerate(ai_runtime.WEIGHTS):
            dest = ai_runtime.REPO_DIR / rel
            if dest.exists() and dest.stat().st_size > 0:
                self._labels[i].setStyleSheet("color:#7fd6a0;font-size:11px;background:transparent;")
                self._labels[i].setText(t("配置済み ✓"))
            else:
                self._labels[i].setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
                self._labels[i].setText(t("未配置"))

    @staticmethod
    def _open(url):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _pick(self, idx: int):
        import ai_runtime
        p, _f = QFileDialog.getOpenFileName(self, t("ダウンロードしたファイルを選択"), "",
                                            "すべて (*)")
        if not p:
            return
        b = ai_runtime.RuntimeBuilder()
        if b.place_weight_file(idx, p):
            self._refresh()
        else:
            QMessageBox.warning(self, t("重みを手動で配置"),
                                t("ファイルの配置に失敗しました。"))


class AiColorConfigDialog(_AiCacheMixin, QDialog):
    """AI着色の接続設定（本棚の⚙設定から開く）。プラグイン選択・接続先・接続テスト・着色データ削除。

    実際の着色はプラグイン側（クラウドAPI / ローカルサーバ / ローカルモデル）。本体は画像を
    渡して受け取るだけ。設定項目はプラグインが宣言したものを動的に描画する。有効化や全ページ
    着色は本を開いた状態のメニューから行う（ここには置かない）。
    """

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        import ai_color
        import ai_runtime
        import plugins
        self.settings = settings
        self._reader = None
        self._cfg = ai_color.merge(getattr(settings, "ai_color", {}) or {})
        # 保存先を設定から復元（準備状況の表示を正しい場所で見るため）
        ai_runtime.set_base_dir(self._cfg["server"].get("runtime_dir") or "")
        self._providers = plugins.colorizers()
        self._field_widgets: dict = {}
        self._pool = QThreadPool.globalInstance()
        self.setWindowTitle(t("🤖 AI着色（接続設定）"))
        self.setMinimumWidth(470)
        self.setStyleSheet(_AI_QSS)

        # 設定項目が多く縦に伸びるので、中身はスクロール領域に入れる（閉じるボタンは下端固定）。
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;} "
                             "QScrollArea > QWidget > QWidget{background:transparent;}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        lay = QVBoxLayout(content); lay.setContentsMargins(18, 16, 18, 6); lay.setSpacing(9)

        note = QLabel(t("白黒ページをプラグイン経由で着色します。送信先をローカル(localhost)に"
                        "すればオフライン・無料で、画像はPCの外に出ません。"))
        note.setWordWrap(True); note.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(note)

        self._build_server_ui(lay)

        if not self._providers:
            self._build_no_plugin(lay)
        else:
            self._build_plugin_ui(lay)

        self._build_cache_row(lay)

        hint = QLabel(t("※ 有効化と「この本を全ページ着色」は、本を開いた状態のメニュー"
                        "「🤖 AI着色」から行います。"))
        hint.setWordWrap(True); hint.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        lay.addWidget(hint)
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        brow = QHBoxLayout(); brow.setContentsMargins(18, 8, 18, 12); brow.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close"); close.clicked.connect(self.accept)
        brow.addWidget(close); outer.addLayout(brow)

        self._apply_enabled_state()

        # 画面に収まる高さに調整（はみ出す分はスクロール）
        screen = self.screen()
        avail = screen.availableGeometry().height() if screen else 900
        want = content.sizeHint().height() + 70
        self.resize(max(self.minimumWidth(), 500), min(want, int(avail * 0.9)))

    # ── 着色サーバ（Piewerが起動）────────────────────────────

    def _build_server_ui(self, lay):
        import ai_color
        import ai_server
        sv = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})["server"]

        sub = QLabel(t("着色サーバ（Piewerが自動で起動）"))
        sub.setStyleSheet("color:#bfa6ff;font-size:12px;font-weight:bold;background:transparent;")
        lay.addSpacing(2); lay.addWidget(sub)

        arow = QHBoxLayout(); arow.setSpacing(8)
        self._setup_btn = QPushButton(t("▶ AI着色を自動で準備する（推奨）"))
        self._setup_btn.setObjectName("close")
        self._setup_btn.clicked.connect(self._open_runtime_setup)
        arow.addWidget(self._setup_btn)
        self._setup_lbl = QLabel(""); self._setup_lbl.setWordWrap(True)
        self._setup_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        arow.addWidget(self._setup_lbl, 1); lay.addLayout(arow)
        self._update_runtime_label()

        self._mng_cb = QCheckBox(t("Piewerでサーバを自動起動する（推奨）"))
        self._mng_cb.setChecked(bool(sv.get("manage")))
        self._mng_cb.stateChanged.connect(self._persist)
        lay.addWidget(self._mng_cb)

        drow = QHBoxLayout(); drow.setSpacing(8)
        drow.addWidget(QLabel(t("処理")))
        self._dev_cb = QComboBox()
        self._dev_cb.addItem(t("GPU (CUDA・速い)"), "cuda")
        self._dev_cb.addItem(t("CPU（遅い・GPU無しでも可）"), "cpu")
        # 未設定（初回）のときだけGPUの有無で自動判定。保存済みならそれを尊重。
        raw = getattr(self.settings, "ai_color", {}) or {}
        raw_sv = raw.get("server") if isinstance(raw.get("server"), dict) else {}
        dev = raw_sv.get("device") or ("cuda" if ai_server.has_nvidia_gpu() else "cpu")
        di = self._dev_cb.findData(dev); self._dev_cb.setCurrentIndex(di if di >= 0 else 0)
        self._dev_cb.currentIndexChanged.connect(self._persist)
        self._dev_cb.currentIndexChanged.connect(self._update_runtime_label)
        drow.addWidget(self._dev_cb, 1); lay.addLayout(drow)

        self._py_edit = self._path_row(lay, t("Python のパス"), sv.get("python", ""),
                                       self._browse_python)
        self._repo_edit = self._path_row(lay, t("モデルのフォルダ"), sv.get("repo", ""),
                                         self._browse_repo)

        prow = QHBoxLayout(); prow.setSpacing(8)
        prow.addWidget(QLabel(t("ポート")))
        self._port_spin = QSpinBox(); self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(int(sv.get("port", 7860)))
        self._port_spin.valueChanged.connect(self._persist)
        prow.addWidget(self._port_spin)
        prow.addSpacing(14); prow.addWidget(QLabel(t("色の濃さ")))
        self._sat_spin = QDoubleSpinBox(); self._sat_spin.setRange(0.2, 3.0)
        self._sat_spin.setSingleStep(0.1); self._sat_spin.setValue(float(sv.get("saturation", 1.0)))
        self._sat_spin.setToolTip(t("1.0=標準。大きいほど鮮やかに、小さいほど淡くなります。"))
        self._sat_spin.valueChanged.connect(self._persist)
        prow.addWidget(self._sat_spin); prow.addStretch()
        lay.addLayout(prow)

        sat_help = QLabel(t("「色の濃さ」は着色の鮮やかさ。1.0 が標準で、数値を大きくするほど色が"
                            "濃く鮮やかに、小さくするほど淡く（モノクロ寄りに）なります。"
                            "変更したらサーバを再起動し、「着色データを削除」で塗り直してください。"))
        sat_help.setWordWrap(True)
        sat_help.setStyleSheet("color:#6f6690;font-size:10px;background:transparent;")
        lay.addWidget(sat_help)

        srow = QHBoxLayout(); srow.setSpacing(8)
        self._srv_btn = QPushButton(t("サーバ起動")); self._srv_btn.clicked.connect(self._toggle_server)
        srow.addWidget(self._srv_btn)
        self._srv_lbl = QLabel(""); self._srv_lbl.setWordWrap(True)
        self._srv_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        srow.addWidget(self._srv_lbl, 1); lay.addLayout(srow)

        shint = QLabel(t("※ 自動起動ONのとき、下の「エンドポイントURL」はサーバ起動時に自動設定されます。"))
        shint.setWordWrap(True); shint.setStyleSheet("color:#6f6690;font-size:10px;background:transparent;")
        lay.addWidget(shint)

        mgr = ai_server.get_manager()
        mgr.status_changed.connect(self._on_srv_status)
        self._on_srv_status(mgr.status, mgr.message)

    def _open_runtime_setup(self, *_):
        dlg = AiRuntimeSetupDialog(self.settings, on_done=self._on_runtime_done, parent=self)
        dlg.exec()
        self._update_runtime_label()

    def _on_runtime_done(self):
        """自動構築が完了したら、サーバ設定欄に反映する。"""
        import ai_color
        sv = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})["server"]
        self._py_edit.setText(sv.get("python", ""))
        self._repo_edit.setText(sv.get("repo", ""))
        self._mng_cb.setChecked(bool(sv.get("manage")))
        di = self._dev_cb.findData(sv.get("device", "cpu"))
        if di >= 0:
            self._dev_cb.setCurrentIndex(di)
        self._update_runtime_label()

    def _update_runtime_label(self):
        import ai_runtime
        dev = self._dev_cb.currentData() if hasattr(self, "_dev_cb") else ""
        if ai_runtime.is_ready(dev):
            self._setup_lbl.setStyleSheet("color:#7fd6a0;font-size:11px;background:transparent;")
            self._setup_lbl.setText(t("準備済み ✓"))
        else:
            stt = ai_runtime.status(dev)
            n = sum(1 for v in stt.values() if v)
            self._setup_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
            self._setup_lbl.setText(t("未準備（{n}/4 完了）").format(n=n) if n else
                                    t("未準備"))

    def _path_row(self, lay, label, value, browse_cb):
        r = QHBoxLayout(); r.setSpacing(8)
        lb = QLabel(label); lb.setMinimumWidth(120); r.addWidget(lb)
        e = QLineEdit(); e.setText(value or ""); e.textChanged.connect(self._persist)
        r.addWidget(e, 1)
        b = QPushButton(t("参照")); b.clicked.connect(browse_cb); r.addWidget(b)
        lay.addLayout(r)
        return e

    def _browse_python(self, *_):
        p, _f = QFileDialog.getOpenFileName(self, t("Python を選択"), "",
                                            "Python (python*.exe);;すべて (*)")
        if p:
            self._py_edit.setText(p)

    def _browse_repo(self, *_):
        p = QFileDialog.getExistingDirectory(self, t("モデルのフォルダを選択"))
        if p:
            self._repo_edit.setText(p)

    def _collect_server(self) -> dict:
        import ai_color
        prev = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})["server"]
        return {"manage": self._mng_cb.isChecked(),
                "python": self._py_edit.text().strip(),
                "repo": self._repo_edit.text().strip(),
                "device": self._dev_cb.currentData() or "cpu",
                "port": int(self._port_spin.value()),
                "saturation": float(self._sat_spin.value()),
                "runtime_dir": prev.get("runtime_dir", "")}

    def _toggle_server(self, *_):
        import ai_server
        mgr = ai_server.get_manager()
        if mgr.is_active():
            mgr.stop()
            return
        self._persist()
        sv = self._collect_server()
        mgr.start(python=sv["python"], repo=sv["repo"], device=sv["device"],
                  port=sv["port"], saturation=sv["saturation"])

    def _on_srv_status(self, status: str, msg: str):
        import ai_server
        active = status in (ai_server.ColorServerManager.STARTING,
                            ai_server.ColorServerManager.RUNNING)
        self._srv_btn.setText(t("サーバ停止") if active else t("サーバ起動"))
        text = {"stopped": t("停止中"), "starting": t("起動中…（初回はモデル読込で時間がかかります）"),
                "running": t("実行中 ✓"), "error": t("エラー: ") + msg[:90]}.get(status, status)
        color = ("#7fd6a0" if status == "running" else
                 "#e08a7f" if status == "error" else "#8a7fa6")
        self._srv_lbl.setStyleSheet(f"color:{color};font-size:11px;background:transparent;")
        self._srv_lbl.setText(text)

    # ── プラグイン未導入時の案内 ────────────────────────────

    def _build_no_plugin(self, lay):
        import plugins
        box = QLabel(t("着色プラグインが見つかりません。\n"
                       "下のフォルダにプラグイン（フォルダ＋plugin.py）を入れると有効になります。"))
        box.setWordWrap(True)
        box.setStyleSheet("color:#ddd;font-size:12px;background:#2b2539;border:1px solid #463d63;"
                          "border-radius:10px;padding:10px 12px;")
        lay.addWidget(box)
        pdir = plugins.ensure_user_plugin_dir()
        path = QLabel(str(pdir)); path.setWordWrap(True)
        path.setStyleSheet("color:#bfa6ff;font-size:11px;background:transparent;")
        lay.addWidget(path)
        r = QHBoxLayout()
        openb = QPushButton(t("プラグインフォルダを開く")); openb.clicked.connect(lambda: self._open_dir(pdir))
        r.addWidget(openb); r.addStretch(); lay.addLayout(r)

    @staticmethod
    def _open_dir(path):
        import os, sys, subprocess
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))   # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    # ── プラグイン設定UI ────────────────────────────────────

    def _build_plugin_ui(self, lay):
        prow = QHBoxLayout(); prow.setSpacing(8)
        prow.addWidget(QLabel(t("プラグイン")))
        self._plugin_cb = QComboBox()
        for prov in self._providers:
            self._plugin_cb.addItem(getattr(prov, "name", prov.id), prov.id)
        idx = self._plugin_cb.findData(self._cfg["plugin"])
        self._plugin_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._plugin_cb.currentIndexChanged.connect(self._on_plugin_changed)
        prow.addWidget(self._plugin_cb, 1); lay.addLayout(prow)

        self._desc = QLabel(""); self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        lay.addWidget(self._desc)

        # プラグイン固有の設定項目をここに動的に並べる
        self._fields_box = QVBoxLayout(); self._fields_box.setSpacing(7)
        lay.addLayout(self._fields_box)

        trow = QHBoxLayout()
        self._test_btn = QPushButton(t("接続テスト")); self._test_btn.clicked.connect(self._test)
        trow.addWidget(self._test_btn)
        self._test_lbl = QLabel(""); self._test_lbl.setWordWrap(True)
        self._test_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        trow.addWidget(self._test_lbl, 1); lay.addLayout(trow)

        self._rebuild_fields()

    def _current_provider(self):
        import plugins
        pid = self._plugin_cb.currentData() if hasattr(self, "_plugin_cb") else self._cfg["plugin"]
        return plugins.get_colorizer(pid)

    def _rebuild_fields(self):
        import plugins
        # 既存のフィールドwidgetを片付ける
        while self._fields_box.count():
            item = self._fields_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._field_widgets.clear()

        prov = self._current_provider()
        if prov is None:
            return
        self._desc.setText(t(getattr(prov, "description", "") or ""))
        opts = self._cfg["opts"] if isinstance(self._cfg.get("opts"), dict) else {}
        for f in plugins.provider_config_fields(prov):
            key = f.get("key")
            if not key:
                continue
            cur = opts.get(key, f.get("default"))
            row = QHBoxLayout(); row.setSpacing(8)
            label = QLabel(t(f.get("label", key))); label.setMinimumWidth(120)
            row.addWidget(label)
            w = self._make_field(f, cur)
            self._field_widgets[key] = w
            row.addWidget(w, 1)
            self._fields_box.addLayout(row)
            help_txt = f.get("help")
            if help_txt:
                h = QLabel(t(help_txt)); h.setWordWrap(True)
                h.setStyleSheet("color:#6f6690;font-size:10px;background:transparent;margin-left:6px;")
                self._fields_box.addWidget(h)

    def _make_field(self, f: dict, cur):
        ftype = f.get("type", "text")
        if ftype == "bool":
            w = QCheckBox(); w.setChecked(bool(cur)); w.stateChanged.connect(self._persist)
            return w
        if ftype == "int":
            w = QSpinBox(); w.setRange(0, 1000000)
            try: w.setValue(int(cur))
            except (TypeError, ValueError): w.setValue(0)
            w.valueChanged.connect(self._persist); return w
        if ftype == "choice":
            w = QComboBox()
            for c in f.get("choices", []):
                w.addItem(str(c), c)
            i = w.findData(cur)
            w.setCurrentIndex(i if i >= 0 else 0)
            w.currentIndexChanged.connect(self._persist); return w
        # text / password
        w = QLineEdit(); w.setText("" if cur is None else str(cur))
        if ftype == "password":
            w.setEchoMode(QLineEdit.EchoMode.Password)
        w.textChanged.connect(self._persist)
        return w

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _collect_opts(self) -> dict:
        out = {}
        for key, w in self._field_widgets.items():
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QLineEdit):
                out[key] = w.text()
        return out

    # ── 保存 ────────────────────────────────────────────────

    def _persist(self, *_):
        """プラグイン選択・接続設定・サーバ設定を保存する（有効化フラグ on は触らない）。"""
        import ai_color
        cur = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})
        if hasattr(self, "_plugin_cb"):
            cur["plugin"] = self._plugin_cb.currentData() or ""
            cur["opts"] = self._collect_opts()
        if hasattr(self, "_mng_cb"):
            server = self._collect_server()
            cur["server"] = server
            # 自動起動ONなら接続先URLはポートから自動導出（手動入力に依存しない）
            if server["manage"]:
                cur["opts"] = {**cur.get("opts", {}),
                               "endpoint": f"http://127.0.0.1:{server['port']}/colorize"}
        self.settings.ai_color = dict(cur)
        self.settings.save()

    def _on_plugin_changed(self, *_):
        self._rebuild_fields()
        self._test_lbl.setText("")
        self._persist()

    def _apply_enabled_state(self):
        en = bool(self._providers)
        if hasattr(self, "_plugin_cb"):
            for w in (self._plugin_cb, self._test_btn):
                w.setEnabled(en)
            for w in self._field_widgets.values():
                w.setEnabled(en)

    def _test(self, *_):
        prov = self._current_provider()
        if prov is None:
            return
        opts = dict(self._collect_opts())
        # テストはサッと終わらせたいので待ち時間を短めに上書き
        if "timeout" in opts:
            try: opts["timeout"] = min(int(opts["timeout"]), 20)
            except (TypeError, ValueError): opts["timeout"] = 20
        self._test_btn.setEnabled(False)
        self._test_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        self._test_lbl.setText(t("テスト中…"))
        worker = _ColorTestWorker(prov, opts)
        worker.signals.done.connect(self._test_done)
        self._pool.start(worker)

    def _test_done(self, ok: bool, msg: str):
        self._test_btn.setEnabled(bool(self._providers))
        color = "#7fd6a0" if ok else "#e08a7f"
        self._test_lbl.setStyleSheet(f"color:{color};font-size:11px;background:transparent;")
        self._test_lbl.setText(("✓ " if ok else "✗ ") + msg)

    def closeEvent(self, e):
        # 入力途中の値も閉じる時点で確定する
        self._persist()
        super().closeEvent(e)


class AiColorDialog(_AiCacheMixin, QDialog):
    """本を開いた状態のメニューから開くAI着色（プラグイン）。

    ここには「有効にする」「この本を全ページ着色」「着色データを削除」だけを置く。
    接続先などの設定は本棚の⚙設定 →「AI着色」（AiColorConfigDialog）で行う。
    """

    def __init__(self, settings, on_change=None, reader=None, parent=None):
        super().__init__(parent)
        import ai_color
        self.settings = settings
        self._on_change = on_change
        self._reader = reader
        self._batch_running = False
        self._cfg = ai_color.merge(getattr(settings, "ai_color", {}) or {})
        self.setWindowTitle(t("🤖 AI着色"))
        self.setMinimumWidth(420)
        self.setStyleSheet(_AI_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(9)

        self._on_cb = QCheckBox(t("AI着色を有効にする（読んでいるページを自動で着色）"))
        self._on_cb.setChecked(bool(self._cfg["on"]))
        self._on_cb.stateChanged.connect(self._toggle_on)
        lay.addWidget(self._on_cb)

        note = QLabel(t("接続先などの設定は、本棚の⚙設定 →「🤖 AI着色」から行います。"))
        note.setWordWrap(True); note.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(note)

        # この本を全ページ着色（バックグラウンドでキャッシュに溜める）
        if self._reader is not None and getattr(self._reader, "source", None) is not None:
            brow = QHBoxLayout(); brow.setSpacing(8)
            self._batch_btn = QPushButton(t("この本を全ページ着色"))
            self._batch_btn.clicked.connect(self._toggle_batch)
            brow.addWidget(self._batch_btn)
            self._batch_lbl = QLabel(""); self._batch_lbl.setWordWrap(True)
            self._batch_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
            brow.addWidget(self._batch_lbl, 1); lay.addLayout(brow)

        self._build_cache_row(lay)

        hint = QLabel(t("※ AI着色は学習からの推測です。実際の色（作者の意図した色）の再現ではなく、"
                        "ページ間で色がぶれることがあります。"))
        hint.setWordWrap(True); hint.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        lay.addWidget(hint)

        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("close"); close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)

    def _persist(self, *_):
        """有効化フラグ on だけを保存（接続設定 plugin/opts はそのまま保つ）。"""
        import ai_color
        cur = ai_color.merge(getattr(self.settings, "ai_color", {}) or {})
        cur["on"] = self._on_cb.isChecked()
        self.settings.ai_color = dict(cur)
        self.settings.save()

    def _apply(self):
        self._persist()
        if self._on_change:
            self._on_change()

    def _toggle_on(self, *_):
        self._apply()

    # ── 全ページ着色 ────────────────────────────────────────

    def _toggle_batch(self, *_):
        r = self._reader
        if r is None or getattr(r, "source", None) is None:
            return
        if self._batch_running:
            r.cancel_batch()
            self._batch_btn.setText(t("中止しています…"))
            self._batch_btn.setEnabled(False)
            return
        # 全ページ着色は表示にも反映させたいので、先に有効化を確定する
        self._on_cb.setChecked(True)
        self._apply()
        if not r.start_batch_colorize(self._on_batch_progress, self._on_batch_finished):
            self._batch_lbl.setStyleSheet("color:#e08a7f;font-size:11px;background:transparent;")
            self._batch_lbl.setText(t("本棚の⚙設定でプラグイン/接続先を設定してください"))
            return
        self._batch_running = True
        self._batch_btn.setText(t("中止"))
        self._batch_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        self._batch_lbl.setText(t("着色中… 0%"))

    def _on_batch_progress(self, done: int, total: int):
        pct = int(done * 100 / total) if total else 0
        self._batch_lbl.setText(t("着色中… {d}/{t} ({p}%)").format(d=done, t=total, p=pct))

    def _on_batch_finished(self, ok: int, total: int, cancelled: bool):
        self._batch_running = False
        self._batch_btn.setEnabled(True)
        self._batch_btn.setText(t("この本を全ページ着色"))
        if cancelled:
            self._batch_lbl.setText(t("中止しました（{ok}/{total} 着色済み）").format(ok=ok, total=total))
        else:
            self._batch_lbl.setStyleSheet("color:#7fd6a0;font-size:11px;background:transparent;")
            self._batch_lbl.setText(t("完了：{ok}/{total} ページ").format(ok=ok, total=total))
        self._update_cache_label()

    def closeEvent(self, e):
        self._apply()
        super().closeEvent(e)


class AiUpscaleDialog(QDialog):
    """AI超解像（プラグイン）の設定＋有効化（リーダーHUDから開く）。

    超解像プラグインは1つ（同梱 local_upscale）想定だが、複数あれば選べる。接続先・
    拡大率をここで設定し、有効化すると「表示より小さいページ」を自動で高精細化する。
    """

    def __init__(self, settings, on_change=None, reader=None, parent=None):
        super().__init__(parent)
        import ai_upscale
        import plugins
        import ai_server
        self.settings = settings
        self._on_change = on_change
        self._reader = reader
        self._cfg = ai_upscale.merge(getattr(settings, "ai_upscale", {}) or {})
        self._providers = list(plugins.upscalers())
        self._pool = QThreadPool.globalInstance()
        self._setting_up = False
        self.setWindowTitle(t("🔍 AI超解像（高解像度化）"))
        self.setMinimumWidth(470)
        self.setStyleSheet(_AI_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 14); lay.setSpacing(9)

        desc = QLabel(t("低解像度のページをAIで高精細に拡大します。表示より小さいページにだけ自動で効きます。"))
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#bbb;font-size:12px;background:transparent;")
        lay.addWidget(desc)

        # ── ① 仕上がりと実行先 ─────────────────────────────
        self._step_label(lay, t("① 仕上がりと実行先を選ぶ"))
        opt = QHBoxLayout(); opt.setSpacing(8)
        opt.addWidget(QLabel(t("拡大")))
        self._scale_cb = QComboBox()
        for label, val in ((t("2倍（速い）"), 2), (t("4倍（精細）"), 4)):
            self._scale_cb.addItem(label, val)
        si = self._scale_cb.findData(int(self._cfg["server"].get("scale", 2)))
        self._scale_cb.setCurrentIndex(si if si >= 0 else 0)
        self._scale_cb.currentIndexChanged.connect(self._on_param_changed)
        opt.addWidget(self._scale_cb)
        opt.addSpacing(12)
        opt.addWidget(QLabel(t("実行")))
        self._dev_cb = QComboBox()
        self._dev_cb.addItem(t("CPU"), "cpu")
        self._dev_cb.addItem(t("GPU(CUDA)"), "cuda")
        di = self._dev_cb.findData(self._cfg["server"].get("device", "cpu"))
        self._dev_cb.setCurrentIndex(di if di >= 0 else 0)
        self._dev_cb.currentIndexChanged.connect(self._on_param_changed)
        opt.addWidget(self._dev_cb); opt.addStretch()
        lay.addLayout(opt)

        # ── ② ワンボタンで準備 ─────────────────────────────
        self._step_label(lay, t("② ボタンひとつで準備する"))
        self._setup_btn = QPushButton(t("▶ 自動でセットアップして有効にする"))
        self._setup_btn.setObjectName("close")   # 主ボタン配色（紫）
        self._setup_btn.setEnabled(bool(self._providers))
        self._setup_btn.clicked.connect(self._auto_setup)
        lay.addWidget(self._setup_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color:#8a7fa6;font-size:12px;background:transparent;")
        lay.addWidget(self._status_lbl)

        # ── ③ 有効/無効 ───────────────────────────────────
        self._on_cb = QCheckBox(t("有効にする（小さいページを自動で高解像度化）"))
        self._on_cb.setChecked(bool(self._cfg["on"]))
        self._on_cb.stateChanged.connect(self._on_toggle_enable)
        lay.addWidget(self._on_cb)

        if not self._providers:
            warn = QLabel(t("超解像プラグインが見つかりません。plugins/local_upscale を確認してください。"))
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#e0b07f;font-size:12px;background:transparent;")
            lay.addWidget(warn)

        # ── 詳細設定（折りたたみ・既定で隠す）──────────────
        self._adv_btn = QPushButton(t("詳細設定 ▾"))
        self._adv_btn.setCheckable(True)
        self._adv_btn.clicked.connect(self._toggle_adv)
        lay.addWidget(self._adv_btn)
        self._adv = QWidget(); self._adv.setStyleSheet("background:transparent;")
        av = QVBoxLayout(self._adv); av.setContentsMargins(0, 4, 0, 0); av.setSpacing(8)
        self._build_advanced(av)
        self._adv.setVisible(False)
        lay.addWidget(self._adv)

        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.setObjectName("flat")
        close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)

        ai_server.get_upscale_manager().status_changed.connect(self._on_srv_status)
        self._sync_endpoint_state()
        self._refresh_status()

    def _step_label(self, lay, text):
        s = QLabel(text)
        s.setStyleSheet("color:#cbb8ff;font-size:12px;font-weight:bold;background:transparent;")
        lay.addSpacing(2); lay.addWidget(s)

    def _build_advanced(self, av):
        """上級者向け設定（自動起動・プラグイン・接続先・データ削除）。"""
        self._manage_cb = QCheckBox(t("Piewerでサーバを自動起動する（推奨）"))
        self._manage_cb.setChecked(bool(self._cfg["server"].get("manage", True)))
        self._manage_cb.stateChanged.connect(self._on_manage_changed)
        av.addWidget(self._manage_cb)

        prow = QHBoxLayout(); prow.setSpacing(8)
        prow.addWidget(QLabel(t("プラグイン")))
        self._plugin_cb = QComboBox()
        for p in self._providers:
            self._plugin_cb.addItem(getattr(p, "name", p.id), p.id)
        pi = self._plugin_cb.findData(self._cfg.get("plugin", ""))
        self._plugin_cb.setCurrentIndex(pi if pi >= 0 else 0)
        self._plugin_cb.currentIndexChanged.connect(self._apply)
        prow.addWidget(self._plugin_cb, 1); av.addLayout(prow)

        erow = QHBoxLayout(); erow.setSpacing(8)
        erow.addWidget(QLabel(t("接続先URL")))
        self._endpoint = QLineEdit(str(self._cfg["opts"].get("endpoint", "")))
        self._endpoint.setPlaceholderText("http://127.0.0.1:7861/upscale")
        self._endpoint.editingFinished.connect(self._apply)
        erow.addWidget(self._endpoint, 1)
        self._test_btn = QPushButton(t("接続テスト"))
        self._test_btn.setEnabled(bool(self._providers))
        self._test_btn.clicked.connect(self._test)
        erow.addWidget(self._test_btn); av.addLayout(erow)

        self._test_lbl = QLabel("")
        self._test_lbl.setWordWrap(True)
        self._test_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        av.addWidget(self._test_lbl)

        self._build_cache_row(av)

    def _toggle_adv(self):
        vis = self._adv_btn.isChecked()
        self._adv.setVisible(vis)
        self._adv_btn.setText(t("詳細設定 ▴") if vis else t("詳細設定 ▾"))
        self.adjustSize()

    # ── かんたんセットアップ（ワンボタン）────────────────────

    def _set_status(self, text: str, kind: str = "muted"):
        colors = {"ok": "#7fd6a0", "err": "#e08a7f", "info": "#bfa6ff", "muted": "#8a7fa6"}
        self._status_lbl.setStyleSheet(
            f"color:{colors.get(kind, '#8a7fa6')};font-size:12px;background:transparent;")
        self._status_lbl.setText(text)

    def _auto_setup(self, *_):
        if self._setting_up:
            return
        if not self._providers:
            self._set_status(t("超解像プラグインが見つかりません。"), "err")
            return
        import ai_runtime
        # 設定を確定（自動起動ON・有効ON・拡大率/実行先）
        self._manage_cb.setChecked(True)
        self._on_cb.blockSignals(True); self._on_cb.setChecked(True); self._on_cb.blockSignals(False)
        self._sync_endpoint_state()
        self._persist()
        scale = int(self._scale_cb.currentData() or 2)
        denoise = int(self._cfg["server"].get("denoise", 1))
        if ai_runtime.cugan_ready(scale, denoise):
            self._set_status(t("準備済み。サーバを起動して有効にします…"), "info")
            self._start_and_enable()
        else:
            self._setting_up = True
            self._setup_btn.setEnabled(False)
            self._set_status(t("Real-CUGAN を準備しています…（初回はダウンロードに時間がかかります）"), "info")
            worker = _CuganPrepWorker(scale, denoise)
            worker.signals.done.connect(self._prep_then_start)
            self._pool.start(worker)

    def _prep_then_start(self, ok: bool, msg: str):
        self._setting_up = False
        self._setup_btn.setEnabled(True)
        if not ok:
            self._set_status(
                t("準備に失敗しました: ") + msg
                + t("（詳細設定で接続先や実行先を確認できます）"), "err")
            return
        self._start_and_enable()

    def _start_and_enable(self):
        """設定を保存し、サーバ起動＋表示反映（readerがあれば経由、無ければ直接）。"""
        self._persist()
        if self._on_change:
            self._on_change()          # reader.apply_ai_upscale → サーバ起動同期＋再描画
        if self._reader is None and self._manage_cb.isChecked():
            self._start_server_standalone()   # readerが無いときは自前で起動
        self._refresh_status()

    def _on_toggle_enable(self, *_):
        self._persist()
        if self._on_cb.isChecked():
            self._start_and_enable()
        else:
            if self._on_change:
                self._on_change()
            self._refresh_status()

    def _on_param_changed(self, *_):
        import ai_server
        self._persist()
        if (self._on_cb.isChecked() and self._manage_cb.isChecked()
                and ai_server.get_upscale_manager().is_active()):
            self._set_status(t("拡大/実行先を変えました。②をもう一度押すと反映されます。"), "info")
        else:
            self._refresh_status()

    def _refresh_status(self):
        import ai_server
        if not self._on_cb.isChecked():
            self._set_status(t("無効です。②を押すと準備して有効にします。"), "muted")
            return
        M = ai_server.UpscaleServerManager
        if not self._manage_cb.isChecked():
            self._set_status(t("✓ 有効（手動の接続先を使用）。"), "ok")
            return
        st = ai_server.get_upscale_manager().status
        if st == M.RUNNING:
            self._set_status(t("✓ 有効・実行中。小さいページが自動で高解像度化されます。"), "ok")
        elif st == M.STARTING:
            self._set_status(t("サーバを起動中…（初回はモデル読込で時間がかかります）"), "info")
        elif st == M.ERROR:
            self._set_status(t("サーバエラー: ") + ai_server.get_upscale_manager().message[:100], "err")
        else:
            self._set_status(t("有効。②を押すとサーバを起動します。"), "info")

    def _on_srv_status(self, status: str, msg: str):
        self._refresh_status()

    def _on_manage_changed(self, *_):
        self._sync_endpoint_state()
        self._apply()
        self._refresh_status()

    def _sync_endpoint_state(self):
        """自動起動ONなら接続先URLはポートから自動導出（手入力を無効化）。"""
        managed = self._manage_cb.isChecked()
        port = int(self._cfg["server"].get("port", 7861))
        if managed:
            self._endpoint.setText(f"http://127.0.0.1:{port}/upscale")
        self._endpoint.setReadOnly(managed)

    def _start_server_standalone(self):
        """reader が無い場合（設定だけ開いたとき）に直接サーバを起動する。"""
        import ai_server, ai_runtime
        sv = self._cfg["server"]
        scale = int(self._scale_cb.currentData() or 2); denoise = int(sv.get("denoise", 1))
        ready = ai_runtime.cugan_ready(scale, denoise)
        python = sv.get("python", "") or (
            str(ai_runtime.runtime_python_exe()) if ai_runtime.python_ready() else "")
        ai_server.get_upscale_manager().start(
            python=python, device=self._dev_cb.currentData(),
            port=int(sv.get("port", 7861)), backend=("cugan" if ready else "demo"),
            repo=str(ai_runtime.cugan_repo_dir()) if ready else "",
            weights_dir=str(ai_runtime.cugan_weights_dir()) if ready else "",
            scale=scale, denoise=denoise)

    # ── 設定の収集/保存 ─────────────────────────────────────

    def _collect_opts(self) -> dict:
        return {"endpoint": self._endpoint.text().strip(), "mode": "multipart",
                "field": "image", "max_side": 0, "timeout": 180}

    def _persist(self, *_):
        import ai_upscale
        cur = ai_upscale.merge(getattr(self.settings, "ai_upscale", {}) or {})
        cur["on"] = self._on_cb.isChecked()
        if self._providers:
            cur["plugin"] = self._plugin_cb.currentData()
        cur["opts"] = self._collect_opts()
        sv = dict(cur["server"])
        sv["scale"] = int(self._scale_cb.currentData() or 2)
        if hasattr(self, "_manage_cb"):
            sv["manage"] = self._manage_cb.isChecked()
            sv["device"] = self._dev_cb.currentData()
        cur["server"] = sv
        self.settings.ai_upscale = dict(cur)
        self.settings.save()

    def _apply(self, *_):
        self._persist()
        if self._on_change:
            self._on_change()

    # ── 接続テスト ──────────────────────────────────────────

    def _current_provider(self):
        import plugins
        if not self._providers:
            return None
        return plugins.get_upscaler(self._plugin_cb.currentData())

    def _test(self, *_):
        prov = self._current_provider()
        if prov is None:
            return
        opts = dict(self._collect_opts())
        opts["timeout"] = 20   # テストは短めに
        self._test_btn.setEnabled(False)
        self._test_lbl.setStyleSheet("color:#8a7fa6;font-size:11px;background:transparent;")
        self._test_lbl.setText(t("テスト中…"))
        worker = _UpscaleTestWorker(prov, opts)
        worker.signals.done.connect(self._test_done)
        self._pool.start(worker)

    def _test_done(self, ok: bool, msg: str):
        self._test_btn.setEnabled(bool(self._providers))
        color = "#7fd6a0" if ok else "#e08a7f"
        self._test_lbl.setStyleSheet(f"color:{color};font-size:11px;background:transparent;")
        self._test_lbl.setText(("✓ " if ok else "✗ ") + msg)

    # ── 高解像度データ（キャッシュ）の容量表示＋全削除 ───────

    def _build_cache_row(self, lay):
        crow = QHBoxLayout(); crow.setSpacing(8)
        self._cache_lbl = QLabel("")
        self._cache_lbl.setStyleSheet("color:#bfa6ff;font-size:12px;background:transparent;")
        crow.addWidget(self._cache_lbl, 1)
        btn = QPushButton(t("高解像度データを削除")); btn.clicked.connect(self._clear_cache_clicked)
        crow.addWidget(btn); lay.addLayout(crow)
        self._update_cache_label()

    def _update_cache_label(self):
        import ai_upscale
        mb = ai_upscale.cache_size_bytes() / (1024 * 1024)
        self._cache_lbl.setText(t("高解像度データ: {mb:.1f} MB").format(mb=mb))

    def _clear_cache_clicked(self, *_):
        import ai_upscale
        if ai_upscale.cache_size_bytes() <= 0:
            self._cache_lbl.setText(t("高解像度データ: 0.0 MB（削除するものはありません）"))
            return
        if QMessageBox.question(self, t("高解像度データの削除"),
                                t("保存済みの高解像度データを全て削除しますか？\n"
                                  "（次に開いたページから作り直されます）"),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                ) != QMessageBox.StandardButton.Yes:
            return
        ai_upscale.clear_cache()
        self._update_cache_label()
        if self._reader is not None:
            self._reader.apply_ai_upscale()

    def closeEvent(self, e):
        self._persist()
        if self._on_change:
            self._on_change()
        super().closeEvent(e)


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

    def __init__(self, library, settings=None, parent=None):
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
        if settings is not None and hasattr(settings, "effective_tag_labels"):
            labels = settings.effective_tag_labels()
        else:
            import auto_tag
            labels = dict(auto_tag.DEFAULT_LABELS)
        view.setHtml(self._build_html(library, labels))
        lay.addWidget(view, 1)
        row = QHBoxLayout(); row.addStretch()
        close = QPushButton(t("閉じる")); close.clicked.connect(self.accept)
        row.addWidget(close); lay.addLayout(row)

    @staticmethod
    def _build_html(library, labels=None) -> str:
        from collections import Counter
        import auto_tag
        lab = dict(auto_tag.DEFAULT_LABELS)
        if labels:
            lab.update({k: v for k, v in labels.items() if k in lab and str(v).strip()})
        artist_pfx = lab["author"] + ":"
        parody_pfx = lab["parody"] + ":"
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
                if tg.startswith(artist_pfx): artist[tg[len(artist_pfx):]] += 1
                elif tg.startswith(parody_pfx): parody[tg[len(parody_pfx):]] += 1

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
        <h2 style='color:{ac};'>✍️ {t("よく読む")}{lab["author"]}</h2>
        <p>{top(artist)}</p>
        <h2 style='color:{ac};'>🎯 {t("よく読む")}{lab["parody"]}</h2>
        <p>{top(parody)}</p>
        """


class TagFilterDialog(QDialog):
    """タグ絞り込み用のウィンドウ。種類ごとに折りたたみ＋検索＋スクロール。

    接頭辞（作者:/サークル:/原作:/イベント:）でカテゴリにまとめ、見出しを開くと
    その一覧（例: イベント → C103 …）が出る。タグが数百〜数千でも辿りやすい。
    複数選択（いずれかに一致でヒット）＋「★お気に入りのみ」。
    """
    # 既定の役割順（設定で分類名が変わってもこの順で先頭に並べる）
    _ROLE_ORDER = ("author", "circle", "parody", "event", "folder")
    _OTHER = "その他"
    # 選択中タグのチップ（はっきり色枠／ホバーで赤＝クリックで解除を示唆）
    SEL_CHIP_QSS = ("QPushButton{background:#a06cff;color:white;border:1px solid #b488ff;"
                    "border-radius:12px;padding:5px 12px;font-size:12px;}"
                    "QPushButton:hover{background:#c4452f;border-color:#e06a52;}")

    def __init__(self, all_tags, selected, fav_on, parent=None, expanded=None, scroll=0,
                 read_state="all", tag_match="or", labels=None):
        super().__init__(parent)
        self._groups = self._compute_groups(all_tags, labels)
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

    def _compute_groups(self, all_tags, labels):
        """見出しの (接頭辞, カテゴリ名) を作る。

        設定された分類名を役割順で先頭に置き、タグに現れる他の「××:」接頭辞も
        自動検出して見出しにする（ユーザーが自由に付けた分類も辿れる）。
        """
        import auto_tag
        lab = dict(auto_tag.DEFAULT_LABELS)
        if labels:
            lab.update({k: v for k, v in labels.items() if k in lab and str(v).strip()})
        groups = []
        seen = set()
        for role in self._ROLE_ORDER:
            cat = lab[role]
            if cat not in seen:
                groups.append((cat + ":", cat)); seen.add(cat)
        # タグに現れる他の接頭辞を自動検出（「分類名:値」形式）
        extra = set()
        for tag in all_tags:
            i = tag.find(":")
            if i > 0:
                cat = tag[:i]
                if cat and cat not in seen:
                    extra.add(cat)
        for cat in sorted(extra):
            groups.append((cat + ":", cat)); seen.add(cat)
        return groups

    def _categorize(self, tag: str):
        for pfx, cat in self._groups:
            if tag.startswith(pfx):
                return cat, tag[len(pfx):]
        return self._OTHER, tag

    def _build_tree(self, all_tags):
        buckets = {cat: [] for _, cat in self._groups}
        buckets[self._OTHER] = []
        for tag in all_tags:
            cat, label = self._categorize(tag)
            buckets[cat].append((label, tag))
        self._total = len(all_tags)
        self._labels = []   # サジェスト用（表示ラベル）
        order = [c for _, c in self._groups] + [self._OTHER]
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
