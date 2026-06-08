import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeView
try:
    from PySide6.QtGui import QFileSystemModel        # Qt6 では QtGui に移動
except ImportError:
    from PySide6.QtWidgets import QFileSystemModel    # 念のためのフォールバック
from PySide6.QtCore import Signal, QDir, QTimer

from widgets import FlatBtn
from i18n import t
from config import SUPPORTED_EXT, RAR_SUPPORT, PDF_SUPPORT


def _archive_filters() -> list[str]:
    """ツリーに表示する開けるファイルのパターン（環境の対応状況に追従）。"""
    pats = ["*.zip", "*.cbz", "*.epub"]
    if RAR_SUPPORT:
        pats += ["*.cbr", "*.rar"]
    if PDF_SUPPORT:
        pats += ["*.pdf"]
    return pats


def _dir_has_images(path: str) -> bool:
    """フォルダ直下に画像があるか（画像フォルダ＝1冊として開けるか）。"""
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_file() and os.path.splitext(e.name)[1].lower() in SUPPORTED_EXT:
                    return True
    except Exception:
        pass
    return False


class FolderBrowserView(QWidget):
    """PCのフォルダをツリーでたどり、本棚に登録せずその場で漫画を開くビュー。

    アーカイブ（zip/cbz/cbr/rar/pdf/epub）はダブルクリックで直接開く。フォルダは
    画像を直接含めば1冊として開け、含まなければ展開してナビゲートする。
    """
    open_requested = Signal(str)   # ファイル or 画像フォルダのパス（登録せず開く）
    go_home = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background:#15121d;")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        header = QWidget(); header.setFixedHeight(60)
        header.setStyleSheet("background:#1f1a29;border-bottom:1px solid #2b2539;")
        hl = QHBoxLayout(header); hl.setContentsMargins(20, 0, 20, 0)
        self._home_btn = FlatBtn(t("⌂ 本棚一覧"), h=34, font_size=13)
        self._home_btn.set_callback(self.go_home.emit)
        hl.addWidget(self._home_btn)
        self._title = QLabel(t("フォルダから開く"))
        self._title.setStyleSheet("color:#ddd;font-size:18px;font-weight:bold;margin-left:12px;")
        hl.addWidget(self._title)
        self._hint = QLabel(t("フォルダ／圧縮ファイルをダブルクリックで開きます"))
        self._hint.setStyleSheet("color:#777;font-size:12px;margin-left:12px;")
        hl.addWidget(self._hint)
        hl.addStretch()
        self._open_btn = FlatBtn(t("📖 このフォルダを開く"), h=34, font_size=13, blue=True)
        self._open_btn.set_callback(self._open_selected_folder)
        hl.addWidget(self._open_btn)
        root.addWidget(header)

        self._model = QFileSystemModel(self)
        self._model.setRootPath("")
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files |
                              QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self._model.setNameFilters(_archive_filters())
        self._model.setNameFilterDisables(False)   # 対象外ファイルは隠す（フォルダは常に表示）

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        for c in (1, 2, 3):           # サイズ/種類/更新日時の列を隠す
            self._tree.hideColumn(c)
        self._tree.setAnimated(True)
        self._tree.setStyleSheet(
            "QTreeView{background:#15121d;color:#ddd;border:none;font-size:13px;outline:none;}"
            "QTreeView::item{padding:4px;}"
            "QTreeView::item:selected{background:#2e2347;color:#fff;}"
            "QTreeView::item:hover{background:#221d31;}"
            "QScrollBar:vertical{background:#18151f;width:14px;}"
            "QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar:horizontal{background:#18151f;height:14px;}"
            "QScrollBar::handle:horizontal{background:#393350;border-radius:7px;min-width:40px;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}")
        self._tree.doubleClicked.connect(self._on_double)
        root.addWidget(self._tree, 1)

    def reveal_last(self):
        """前回開いていた場所（無ければホーム）を選択・展開する。"""
        path = getattr(self.settings, "browse_path", "") or QDir.homePath()

        def _go(retries=8):
            idx = self._model.index(path)
            if not idx.isValid():
                idx = self._model.index(QDir.homePath())
            if idx.isValid():
                self._tree.setCurrentIndex(idx)
                self._tree.scrollTo(idx, QTreeView.ScrollHint.PositionAtCenter)
                self._tree.expand(idx)
            elif retries > 0:
                QTimer.singleShot(60, lambda: _go(retries - 1))
        QTimer.singleShot(0, _go)

    def _remember(self, path: str):
        self.settings.browse_path = path
        self.settings.save()

    def _on_double(self, index):
        path = self._model.filePath(index)
        if self._model.isDir(index):
            if _dir_has_images(path):
                self._remember(os.path.dirname(path))
                self.open_requested.emit(path)
            else:
                self._tree.setExpanded(index, not self._tree.isExpanded(index))
                self._remember(path)
        else:
            self._remember(os.path.dirname(path))
            self.open_requested.emit(path)

    def _open_selected_folder(self):
        idx = self._tree.currentIndex()
        if idx.isValid() and self._model.isDir(idx):
            path = self._model.filePath(idx)
            self._remember(os.path.dirname(path))
            self.open_requested.emit(path)

    def retranslate(self):
        self._home_btn.setText(t("⌂ 本棚一覧"))
        self._title.setText(t("フォルダから開く"))
        self._hint.setText(t("フォルダ／圧縮ファイルをダブルクリックで開きます"))
        self._open_btn.setText(t("📖 このフォルダを開く"))
