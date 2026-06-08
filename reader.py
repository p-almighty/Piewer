import io

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QLineEdit, QMenu,
    QScroller, QApplication
)
from PySide6.QtCore import (Qt, Signal, QTimer, QEvent, QPoint, QRect, QElapsedTimer,
                            QPropertyAnimation, QEasingCurve, QAbstractAnimation)
from PySide6.QtGui import QPixmap, QPainter, QColor, QImage, QFont, QPen, QKeySequence, QPolygon

from config import PageSource, DEFAULT_SHORTCUTS
from image_utils import bytes_to_pixmap, combine_spread, apply_exif
from widgets import FlatBtn, ToggleBtn
from i18n import t

from PIL import Image


class _AnimPlayer:
    """アニメーション画像（動くGIF/WebP/APNG）をページ内で再生する。

    PIL でフレームを1枚ずつ seek してデコードし、各フレームの duration に合わせて
    SwipeDisplay の表示画像を差し替える。メインスレッドのみで動作（スレッド不使用）。
    """

    def __init__(self, display):
        self._display = display
        self._img = None
        self._buf = None
        self._n = 0
        self._frame = 0
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    def start(self, data: bytes) -> bool:
        """アニメーションなら再生開始して True。静止画なら何もせず False。"""
        self.stop()
        try:
            buf = io.BytesIO(data)
            im = Image.open(buf)
            if not getattr(im, "is_animated", False) or getattr(im, "n_frames", 1) < 2:
                return False
        except Exception:
            return False
        self._buf = buf
        self._img = im
        self._n = im.n_frames
        self._frame = 0          # フレーム0は静止画として既に表示済み
        self._schedule()
        return True

    def _schedule(self):
        try:
            dur = int(self._img.info.get("duration", 100) or 100)
        except Exception:
            dur = 100
        self._timer.start(max(20, dur))   # 短すぎるコマは20msで下限

    def _advance(self):
        if self._img is None:
            return
        self._frame = (self._frame + 1) % self._n
        try:
            self._img.seek(self._frame)
            frame = self._img.convert("RGB")
            raw = frame.tobytes()
            qimg = QImage(raw, frame.width, frame.height,
                          frame.width * 3, QImage.Format.Format_RGB888)
            self._display.set_anim_frame(QPixmap.fromImage(qimg))
        except Exception:
            self.stop()
            return
        self._schedule()

    def stop(self):
        self._timer.stop()
        if self._img is not None:
            try:
                self._img.close()
            except Exception:
                pass
        self._img = None
        self._buf = None
        self._n = 0
        self._frame = 0


class SwipeDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cur: QPixmap = QPixmap()
        self._adj: QPixmap = QPixmap()
        self._adj_dir: int = 0
        self._offset: float = 0.0
        self._zoom: float = 1.0
        self._pan_x: int = 0
        self._pan_y: int = 0
        self._fit: str = "height"   # "height"=高さ合わせ / "width"=幅合わせ
        self._voff: int = 0         # 幅合わせ時の縦スクロール量(0=上端)
        self._anim_target: int = 0
        self._anim_cb = None
        self._anim_start: float = 0.0      # アニメーション開始時のoffset
        self._anim_duration: int = 200     # アニメーション時間(ms)
        self._anim_clock = QElapsedTimer() # 経過時間計測
        self._scaled_cache: dict = {}
        screen = __import__('PySide6.QtWidgets', fromlist=['QApplication']).QApplication.primaryScreen()
        fps = max(30.0, min(360.0, screen.refreshRate() if screen else 60.0))
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(4, round(1000.0 / fps)))
        self._timer.timeout.connect(self._tick)
        self.setStyleSheet("background:#131019;")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def zoom(self) -> float: return self._zoom

    def set_current(self, cur: QPixmap, adj: QPixmap, adj_dir: int):
        self._cur = cur; self._adj = adj; self._adj_dir = adj_dir
        self._offset = 0.0; self._zoom = 1.0; self._pan_x = 0; self._pan_y = 0
        self._voff = 0
        self._timer.stop(); self.update()

    def set_anim_frame(self, px: QPixmap):
        """アニメーションの1フレームを表示（ズーム/フィット状態は保持）。"""
        if px.isNull(): return
        self._cur = px
        self.update()

    def set_fit(self, mode: str):
        if mode not in ("height", "width", "contain"): return
        # フィット設定が変わらないならスケールキャッシュを保持する。
        # （連続めくりでは、隣ページがアニメ中に平滑スケール済み→そのまま現在ページに
        #  なるため、着地ごとに再スケールせずに済み軽くなる。set_current 側で _voff/
        #  _zoom はリセット済みなのでここで触る必要はない。）
        if mode == self._fit:
            return
        self._fit = mode; self._voff = 0; self._zoom = 1.0
        self._scaled_cache.clear(); self.update()

    def _scaled_h(self, px: QPixmap) -> int:
        """現在のフィット設定でのページ表示高さ。"""
        if self._fit == "width" and px.width() > 0:
            return int(px.height() * self.width() / px.width())
        return self.height()

    def scroll_v(self, dy: int):
        """幅合わせ時の縦スクロール（dy>0で上方向へ）。"""
        if self._cur.isNull(): return
        maxv = max(0, self._scaled_h(self._cur) - self.height())
        self._voff = max(0, min(maxv, self._voff - dy))
        self.update()

    def set_offset(self, dx: int):
        self._offset = float(dx); self.update()

    def animate_to(self, target: int, cb=None, duration: int = 200):
        self._anim_target = target; self._anim_cb = cb
        self._anim_start = self._offset
        self._anim_duration = max(1, duration)
        self._anim_clock.restart()
        self._timer.start()

    def set_zoom(self, z: float):
        self._zoom = z
        if z <= 1.0: self._pan_x = 0; self._pan_y = 0
        self.update()

    def zoom_at(self, new_zoom: float, ax: int, ay: int):
        """スクリーン座標(ax,ay)を固定点としてズーム（マウスポインタに向かって拡大縮小）。"""
        new_zoom = max(1.0, min(8.0, new_zoom))
        cur = self._cur
        if new_zoom <= 1.0 or cur.isNull() or cur.width() <= 0 or cur.height() <= 0:
            self.set_zoom(new_zoom); return
        w, h = self.width(), self.height()
        # 現在の表示サイズと左上座標（paintEvent と同じ式）
        old_sh = h * self._zoom
        old_sw = cur.width() * old_sh / cur.height()
        x0 = (w - old_sw) / 2 - self._pan_x
        y0 = (h - old_sh) / 2 - self._pan_y
        # アンカー位置の画像内割合（余白クリックでも暴れないよう[0,1]に丸める）
        fx = min(1.0, max(0.0, (ax - x0) / old_sw)) if old_sw else 0.5
        fy = min(1.0, max(0.0, (ay - y0) / old_sh)) if old_sh else 0.5
        # 新しい表示サイズで同じ割合が(ax,ay)に来るよう左上→panを逆算。
        # ここでは pan をクランプしない：画像が画面より狭い段階でも中央へ寄せず、
        # 最初からポインタ位置を固定して拡大する（アンカーは常に画面内なので飛ばない）。
        new_sh = h * new_zoom
        new_sw = cur.width() * new_sh / cur.height()
        self._zoom = new_zoom
        self._pan_x = int((w - new_sw) / 2 - (ax - fx * new_sw))
        self._pan_y = int((h - new_sh) / 2 - (ay - fy * new_sh))
        self.update()

    def pan(self, dx: int, dy: int):
        if self._cur.isNull(): return
        h = self.height(); z = self._zoom
        sh = int(h * z)
        sw = int(self._cur.width() * sh / self._cur.height()) if self._cur.height() > 0 else self.width()
        max_x = max(0, (sw - self.width()) // 2)
        max_y = max(0, (sh - h) // 2)
        self._pan_x = max(-max_x, min(max_x, self._pan_x - dx))
        self._pan_y = max(-max_y, min(max_y, self._pan_y - dy))
        self.update()

    def _tick(self):
        # 時間ベースのイーズアウト：指定時間で目標にぴったり着地する（終端のジャンプなし）
        t = self._anim_clock.elapsed() / self._anim_duration
        if t >= 1.0:
            self._offset = float(self._anim_target)
            self._timer.stop()
            if self._anim_cb:
                cb = self._anim_cb; self._anim_cb = None; cb()
        else:
            # ease-out cubic: 1-(1-t)^3 で滑らかに減速しつつ確実に到達
            e = 1.0 - (1.0 - t) ** 3
            self._offset = self._anim_start + (self._anim_target - self._anim_start) * e
        self.update()

    def _scaled(self, px: QPixmap, w: int, h: int) -> QPixmap:
        # id(px) はメモリアドレス再利用で衝突するため cacheKey() を使用する
        if self._fit == "contain":
            key = (px.cacheKey(), "contain", (w, h))
        else:
            key = (px.cacheKey(), self._fit, w if self._fit == "width" else h)
        if key not in self._scaled_cache:
            if len(self._scaled_cache) > 12:
                self._scaled_cache.clear()
            sm = Qt.TransformationMode.SmoothTransformation
            if self._fit == "contain":   # 画面内に全体が収まるよう縦横とも収める
                self._scaled_cache[key] = px.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, sm)
            elif self._fit == "width":
                self._scaled_cache[key] = px.scaledToWidth(w, sm)
            else:
                self._scaled_cache[key] = px.scaledToHeight(h, sm)
        return self._scaled_cache[key]

    def _draw(self, p: QPainter, px: QPixmap, cx: int, h: int):
        if px.isNull(): return
        s = self._scaled(px, self.width(), h)
        x = cx - s.width() // 2
        if self._fit == "width" and s.height() > h:
            y = -self._voff                 # 上端基準でスクロール
        else:
            y = (h - s.height()) // 2       # 縦方向は中央寄せ
        p.drawPixmap(x, y, s)

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#131019"))
        if self._cur.isNull(): p.end(); return
        if self._zoom > 1.0:
            sh = int(h * self._zoom)
            s = self._cur.scaledToHeight(sh, Qt.TransformationMode.SmoothTransformation)
            x = (w - s.width()) // 2 - self._pan_x
            y = (h - sh) // 2 - self._pan_y
            p.drawPixmap(x, y, s)
        else:
            off = round(self._offset)
            self._draw(p, self._cur, w // 2 + off, h)
            if off < 0 and not self._adj.isNull() and self._adj_dir == -1:
                self._draw(p, self._adj, w // 2 + w + off, h)
            elif off > 0 and not self._adj.isNull() and self._adj_dir == 1:
                self._draw(p, self._adj, w // 2 - w + off, h)
        p.end()


class PageThumbStrip(QWidget):
    """全ページのサムネイルを QPainter で直接描画する横スクロールストリップ。

    QLabel/QScrollArea のレイアウト問題を避けるため、すべて自前で描画する。
    """
    page_clicked = Signal(int)
    TW, TH = 156, 216         # サムネイル最大サイズ（さらに1.5倍）
    GAP = 16                  # アイテム間の余白
    MARGIN_L = 14             # 左端の余白
    TOP = 14                  # 上端の余白（サムネイルの開始Y）
    STRIP_H = 272             # ストリップ全体の高さ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._current = 0
        self._cur_count = 1                     # 現在表示中のページ数（見開きなら2）
        self._n = 0
        self._rtl = True                        # True=右が1ページ目（右綴じ漫画）
        self._thumbs: dict[int, QPixmap] = {}   # ページ -> サムネイル
        self._failed: set[int] = set()          # 読み込み失敗ページ
        self._bookmarks: set[int] = set()       # しおりが付いたページ
        self._queue: list[int] = []             # 読み込み待ち
        self._processing = False
        self._scroll_x = 0                      # 横スクロール量(px)
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def _item_w(self) -> int:
        return self.TW + self.GAP

    def _col(self, page: int) -> int:
        """ページ番号 → 表示列。RTLなら page 0 が最も右の列。"""
        return (self._n - 1 - page) if self._rtl else page

    def _page(self, col: int) -> int:
        """表示列 → ページ番号。"""
        return (self._n - 1 - col) if self._rtl else col

    def _max_scroll(self) -> int:
        total = self.MARGIN_L * 2 + self._n * self._item_w
        return max(0, total - self.width())

    def set_source(self, source, current: int, rtl: bool = True, count: int = 1):
        self._source = source
        self._n = len(source)
        self._rtl = rtl
        self._thumbs.clear(); self._failed.clear()
        self._queue.clear(); self._processing = False
        self._scroll_x = 0
        self._current = current
        self._cur_count = max(1, count)
        self._ensure_current_visible()
        self.update()
        QTimer.singleShot(0, self._load_visible)
        QTimer.singleShot(120, self._load_visible)

    def set_rtl(self, rtl: bool):
        if rtl == self._rtl: return
        self._rtl = rtl
        self._ensure_current_visible()
        self.update()
        self._load_visible()

    def set_current(self, idx: int, count: int = 1):
        self._current = idx
        self._cur_count = max(1, count)
        self._ensure_current_visible()
        self.update()
        self._load_visible()

    def set_bookmarks(self, bookmarks):
        self._bookmarks = {int(p) for p in bookmarks}
        self.update()

    def _ensure_current_visible(self):
        if not (0 <= self._current < self._n) or self.width() <= 0:
            return
        item_x = self.MARGIN_L + self._col(self._current) * self._item_w
        if item_x < self._scroll_x:
            self._scroll_x = item_x
        elif item_x + self._item_w > self._scroll_x + self.width():
            self._scroll_x = item_x + self._item_w - self.width()
        self._scroll_x = max(0, min(self._scroll_x, self._max_scroll()))

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        self._scroll_x = max(0, min(self._scroll_x - dy, self._max_scroll()))
        self.update()
        self._load_visible()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mx = event.position().toPoint().x() + self._scroll_x - self.MARGIN_L
        if mx < 0:
            return
        col = mx // self._item_w
        page = self._page(int(col))
        if 0 <= page < self._n:
            self.page_clicked.emit(page)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scroll_x = max(0, min(self._scroll_x, self._max_scroll()))
        self._load_visible()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(20, self._load_visible)

    # ── 描画 ────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(12, 12, 12, 235))
        if self._n <= 0:
            p.end(); return

        first_col = max(0, (self._scroll_x - self.MARGIN_L) // self._item_w)
        last_col = min(self._n - 1, (self._scroll_x + w - self.MARGIN_L) // self._item_w)

        # 現在表示中のページ集合（見開きなら2ページ）
        cur_pages = {self._current}
        if self._cur_count >= 2 and self._current + 1 < self._n:
            cur_pages.add(self._current + 1)
        cur_boxes = []  # 緑枠を後でまとめて描くための矩形リスト

        f = QFont(); f.setPointSize(12); p.setFont(f)
        for col in range(int(first_col), int(last_col) + 1):
            i = self._page(col)
            slot_x = self.MARGIN_L + col * self._item_w - self._scroll_x
            box = QRect(slot_x, self.TOP, self.TW, self.TH)
            is_cur = (i in cur_pages)
            if is_cur:
                cur_boxes.append(box)

            px = self._thumbs.get(i)
            if px is not None and not px.isNull():
                sx = box.x() + (self.TW - px.width()) // 2
                sy = box.y() + (self.TH - px.height()) // 2
                p.fillRect(box, QColor(20, 20, 20))
                p.drawPixmap(sx, sy, px)
            else:
                p.fillRect(box, QColor(37, 37, 37))
                p.setPen(QColor(120, 120, 120))
                txt = "×" if i in self._failed else "…"
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, txt)

            # 通常の細い枠線（現在ページは緑枠を後で重ねるのでスキップ）
            if not is_cur:
                p.setPen(QColor(70, 70, 70))
                p.drawRect(box.adjusted(0, 0, -1, -1))

            # しおり：右上に金色のリボン
            if i in self._bookmarks:
                bx = box.right()
                tri = QPolygon([QPoint(bx - 26, box.top()), QPoint(bx, box.top()),
                                QPoint(bx, box.top() + 34)])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0xff, 0xc1, 0x07))
                p.drawPolygon(tri)
                p.setBrush(Qt.BrushStyle.NoBrush)

            # ページ番号
            p.setPen(QColor(0x66, 0xdd, 0x66) if is_cur else QColor(150, 150, 150))
            num_rect = QRect(slot_x, self.TOP + self.TH + 2, self.TW, 22)
            p.drawText(num_rect, Qt.AlignmentFlag.AlignCenter, str(i + 1))

        # 現在ページ（見開きなら2枚まとめて）を大きな緑枠で囲む
        if cur_boxes:
            left = min(b.left() for b in cur_boxes)
            right = max(b.right() for b in cur_boxes)
            top = cur_boxes[0].top()
            bottom = cur_boxes[0].bottom()
            green_rect = QRect(left, top, right - left + 1, bottom - top + 1).adjusted(-5, -5, 5, 5)
            pen = QPen(QColor(0x33, 0xdd, 0x44), 5)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(green_rect)
        p.end()

    # ── 遅延ロード（メインスレッドで1枚ずつ）────────────────

    def _load_visible(self):
        if not self._source or self._n <= 0 or self.width() <= 0:
            return
        w = self.width()
        first_col = max(0, (self._scroll_x - self.MARGIN_L) // self._item_w - 1)
        last_col = min(self._n - 1, (self._scroll_x + w - self.MARGIN_L) // self._item_w + 1)
        for col in range(int(first_col), int(last_col) + 1):
            i = self._page(col)
            if i not in self._thumbs and i not in self._failed and i not in self._queue:
                self._queue.append(i)
        self._kick_queue()

    def _kick_queue(self):
        if self._queue and not self._processing:
            self._processing = True
            QTimer.singleShot(0, self._process_one)

    def _process_one(self):
        # 1ティックあたり最大3枚処理（draftで高速なのでUIをブロックしない）
        for _ in range(3):
            if not self._queue or not self._source:
                break
            idx = self._queue.pop(0)
            if idx in self._thumbs or idx in self._failed:
                continue
            try:
                data = self._source.read(idx)
                img = Image.open(io.BytesIO(data))
                # JPEGはdraftで低解像度デコードして大幅高速化（非JPEGは無視される）
                img.draft("RGB", (self.TW * 2, self.TH * 2))
                img = apply_exif(img).convert("RGB")
                img.thumbnail((self.TW, self.TH), Image.BILINEAR)
                qimg = QImage(img.tobytes(), img.width, img.height,
                              img.width * 3, QImage.Format.Format_RGB888).copy()
                self._thumbs[idx] = QPixmap.fromImage(qimg)
            except Exception:
                self._failed.add(idx)
        self.update()
        self._processing = False
        self._kick_queue()


class _GridCanvas(QWidget):
    """PageGridView の描画キャンバス（描画・クリックを親 PageGridView へ委譲）。"""

    def __init__(self, grid):
        super().__init__()
        self._grid = grid
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        self._grid._paint(self, event)

    def mousePressEvent(self, event):
        self._grid._on_click(event)


class PageGridView(QScrollArea):
    """全ページのサムネイルを格子状に並べる目次オーバーレイ。

    PageThumbStrip と同じ「メインスレッドで遅延ロード（draftデコード・3枚/tick）」
    方式を踏襲（PySide6でのスレッド間画像受け渡しが不安定なため）。クリックで
    そのページへジャンプする。
    """
    page_clicked = Signal(int)
    closed = Signal()
    TW, TH = 128, 178         # サムネイル最大サイズ
    LABEL_H = 22              # ページ番号ラベルの高さ
    GAP = 14                  # セル間の余白
    MARGIN = 18               # 外周の余白

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea{border:none;background:#121018;} "
            "QScrollBar:vertical{background:#18151f;width:14px;} "
            "QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;} "
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self._source = None
        self._n = 0
        self._rtl = True
        self._current = 0
        self._cols = 1
        self._left = self.MARGIN
        self._thumbs: dict[int, QPixmap] = {}
        self._failed: set[int] = set()
        self._bookmarks: set[int] = set()
        self._queue: list[int] = []
        self._processing = False
        self._canvas = _GridCanvas(self)
        self.setWidget(self._canvas)
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._load_visible())

    @property
    def _cell_w(self) -> int:
        return self.TW + self.GAP

    @property
    def _cell_h(self) -> int:
        return self.TH + self.LABEL_H + self.GAP

    def set_source(self, source, current: int, rtl: bool = True, bookmarks=None):
        self._source = source
        self._n = len(source) if source else 0
        self._rtl = rtl
        self._current = current
        self._bookmarks = {int(p) for p in (bookmarks or [])}
        self._thumbs.clear(); self._failed.clear()
        self._queue.clear(); self._processing = False
        self._relayout()
        self._scroll_to_current()
        self._canvas.update()
        QTimer.singleShot(0, self._load_visible)
        QTimer.singleShot(120, self._load_visible)

    def _relayout(self):
        vw = self.viewport().width()
        if vw <= 0:
            return
        self._cols = max(1, (vw - self.MARGIN) // self._cell_w)
        rows = (self._n + self._cols - 1) // self._cols if self._n else 0
        grid_w = self._cols * self._cell_w
        self._left = max(self.MARGIN, (vw - grid_w) // 2)
        h = self.MARGIN * 2 + rows * self._cell_h
        self._canvas.resize(vw, max(h, self.viewport().height()))

    def _scroll_to_current(self):
        if not (0 <= self._current < self._n) or self._cols <= 0:
            return
        row = self._current // self._cols
        y = self.MARGIN + row * self._cell_h
        self.verticalScrollBar().setValue(
            max(0, y - self.viewport().height() // 2 + self._cell_h // 2))

    def _cell_rect(self, page: int) -> QRect:
        row = page // self._cols
        pos = page % self._cols
        col = (self._cols - 1 - pos) if self._rtl else pos   # RTLは右から並べる
        x = self._left + col * self._cell_w
        y = self.MARGIN + row * self._cell_h
        return QRect(x, y, self.TW, self.TH)

    def _page_at(self, pt: QPoint) -> int:
        if self._cols <= 0:
            return -1
        col = (pt.x() - self._left) // self._cell_w
        row = (pt.y() - self.MARGIN) // self._cell_h
        if col < 0 or col >= self._cols or row < 0:
            return -1
        pos = (self._cols - 1 - col) if self._rtl else col
        page = int(row * self._cols + pos)
        return page if 0 <= page < self._n else -1

    def _visible_pages(self):
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        first_row = max(0, (top - self.MARGIN) // self._cell_h - 1)
        last_row = (bottom - self.MARGIN) // self._cell_h + 1
        for row in range(int(first_row), int(last_row) + 1):
            for c in range(self._cols):
                page = row * self._cols + c
                if 0 <= page < self._n:
                    yield page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()
        self._scroll_to_current()
        self._load_visible()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit(); return
        super().keyPressEvent(event)

    def _on_click(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        page = self._page_at(event.position().toPoint())
        if 0 <= page < self._n:
            self.page_clicked.emit(page)

    # ── 描画 ────────────────────────────────────────────────

    def _paint(self, canvas, event):
        p = QPainter(canvas)
        p.fillRect(event.rect(), QColor(18, 16, 24))
        if self._n <= 0:
            p.end(); return
        f = QFont(); f.setPointSize(11); p.setFont(f)
        for page in self._visible_pages():
            box = self._cell_rect(page)
            is_cur = (page == self._current)
            px = self._thumbs.get(page)
            if px is not None and not px.isNull():
                sx = box.x() + (self.TW - px.width()) // 2
                sy = box.y() + (self.TH - px.height()) // 2
                p.fillRect(box, QColor(20, 20, 20))
                p.drawPixmap(sx, sy, px)
            else:
                p.fillRect(box, QColor(37, 37, 37))
                p.setPen(QColor(120, 120, 120))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter,
                           "×" if page in self._failed else "…")
            if is_cur:
                pen = QPen(QColor(0x33, 0xdd, 0x44), 4)
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(box.adjusted(-3, -3, 3, 3))
            else:
                p.setPen(QColor(70, 70, 70))
                p.drawRect(box.adjusted(0, 0, -1, -1))
            if page in self._bookmarks:
                bx = box.right()
                tri = QPolygon([QPoint(bx - 22, box.top()), QPoint(bx, box.top()),
                                QPoint(bx, box.top() + 30)])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0xff, 0xc1, 0x07))
                p.drawPolygon(tri)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(0x66, 0xdd, 0x66) if is_cur else QColor(170, 170, 170))
            num = QRect(box.x(), box.bottom() + 3, self.TW, self.LABEL_H)
            p.drawText(num, Qt.AlignmentFlag.AlignCenter, str(page + 1))
        p.end()

    # ── 遅延ロード（メインスレッドで1ティック3枚ずつ）────────

    def _load_visible(self):
        if not self._source or self._n <= 0 or self.viewport().width() <= 0:
            return
        for page in self._visible_pages():
            if page not in self._thumbs and page not in self._failed and page not in self._queue:
                self._queue.append(page)
        self._kick_queue()

    def _kick_queue(self):
        if self._queue and not self._processing:
            self._processing = True
            QTimer.singleShot(0, self._process_one)

    def _process_one(self):
        for _ in range(3):
            if not self._queue or not self._source:
                break
            idx = self._queue.pop(0)
            if idx in self._thumbs or idx in self._failed:
                continue
            try:
                data = self._source.read(idx)
                img = Image.open(io.BytesIO(data))
                img.draft("RGB", (self.TW * 2, self.TH * 2))
                img = apply_exif(img).convert("RGB")
                img.thumbnail((self.TW, self.TH), Image.BILINEAR)
                qimg = QImage(img.tobytes(), img.width, img.height,
                              img.width * 3, QImage.Format.Format_RGB888).copy()
                self._thumbs[idx] = QPixmap.fromImage(qimg)
            except Exception:
                self._failed.add(idx)
        self._canvas.update()
        self._processing = False
        self._kick_queue()


class WebtoonView(QScrollArea):
    """縦読み（Webtoon）用の連続縦スクロール表示。

    全ページを縦に並べ、幅に合わせて表示。可視範囲のみ遅延ロードし、
    画面外のページは解放してメモリを抑える（高さは保持してレイアウトを安定させる）。
    """
    page_changed = Signal(int)
    clicked = Signal()      # 画面クリック（HUD トグル用）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea{border:none;background:#131019;} "
            "QScrollBar:vertical{background:#18151f;width:14px;} "
            "QScrollBar::handle:vertical{background:#393350;border-radius:7px;min-height:40px;} "
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self._content = QWidget(); self._content.setStyleSheet("background:#131019;")
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0); self._vbox.setSpacing(2)
        self._vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._content)
        self.viewport().installEventFilter(self)   # ホイール=ページ送り / クリック=HUD
        # タッチは慣性スクロール（QScroller）で処理。マウスは上の eventFilter で処理。
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self._source = None
        self._labels: list[QLabel] = []
        self._loaded: dict[int, bool] = {}
        self._current = 0
        self._press = None          # クリック/ドラッグ判定用の押下位置
        self._moved = False
        self._dragging = False       # ドラッグ追従中（この間はデコードしない）
        self._drag_start_scroll = 0  # ドラッグ開始時のスクロール位置
        self._drag_start_page = 0    # ドラッグ開始時のページ
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._load_timer = QTimer(self); self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._update_visible)
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _page_width(self) -> int:
        return max(200, self.viewport().width())

    def _page_height(self) -> int:
        return max(200, self.viewport().height())

    def set_source(self, source, start_page: int = 0):
        for lb in self._labels:
            lb.deleteLater()
        self._labels = []; self._loaded = {}
        self._source = source
        n = len(source) if source else 0
        ph = self._page_height()   # 1ページ＝1画面（高さ合わせ）
        for _ in range(n):
            lb = QLabel(); lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet("background:#131019;color:#393350;font-size:13px;")
            lb.setText("…"); lb.setFixedHeight(ph)
            self._vbox.addWidget(lb); self._labels.append(lb)
        self._current = max(0, min(start_page, n - 1)) if n else 0
        self._update_visible()   # 開いた直後に現在ページ周辺を先読み
        QTimer.singleShot(0, lambda: self.jump_to(self._current))
        QTimer.singleShot(0, self._update_visible)

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            t = event.type()
            if t == QEvent.Type.Wheel:
                # ホイールでページ遷移（下=次 / 上=前）
                self.step(1 if event.angleDelta().y() < 0 else -1)
                return True
            if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._press = event.position().toPoint(); self._moved = False
                self._drag_start_scroll = self.verticalScrollBar().value()
                self._drag_start_page = self._current
                self._anim.stop(); self._load_timer.stop()   # 追従中のデコードを止める
                return True
            if t == QEvent.Type.MouseMove and self._press is not None:
                d = event.position().toPoint() - self._press
                if not self._moved and abs(d.x()) + abs(d.y()) > 10:
                    self._moved = True; self._dragging = True
                if self._moved:
                    # 上下ドラッグにコンテンツを追従させる（横方向は無視）
                    self.verticalScrollBar().setValue(int(self._drag_start_scroll - d.y()))
                return True
            if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton \
                    and self._press is not None:
                d = event.position().toPoint() - self._press
                x = event.position().toPoint().x(); self._press = None
                self._dragging = False
                if self._moved:
                    # 少量のドラッグでページ遷移：上=次/下=前、しきい値未満は元に戻す
                    thr = max(40, self._page_height() * 0.1)
                    if d.y() <= -thr:
                        self.jump_to(min(self._drag_start_page + 1, len(self._labels) - 1), animate=True)
                    elif d.y() >= thr:
                        self.jump_to(max(self._drag_start_page - 1, 0), animate=True)
                    else:
                        self.jump_to(self._drag_start_page, animate=True)
                else:
                    # クリック：左端＝次、右端＝前、中央＝HUD
                    w3 = self.viewport().width() / 3
                    if x < w3: self.step(1)
                    elif x > w3 * 2: self.step(-1)
                    else: self.clicked.emit()
                return True
        return super().eventFilter(obj, event)

    def _on_scroll(self, _):
        self._update_current()
        # ドラッグ追従中・アニメ中はデコードしない（引っかかり防止）。
        # 隣接ページは先読み済みなので表示は途切れない。
        if not self._dragging and self._anim.state() != QAbstractAnimation.State.Running:
            self._load_timer.start(20)

    def _update_current(self):
        if not self._labels: return
        # ページ送りアニメ中は step 側が現在ページを管理する
        if self._anim.state() == QAbstractAnimation.State.Running:
            return
        y = self.verticalScrollBar().value()
        for i, lb in enumerate(self._labels):
            if lb.y() + lb.height() > y + 4:
                if i != self._current:
                    self._current = i; self.page_changed.emit(i)
                return

    def _update_visible(self):
        if not self._source or not self._labels: return
        n = len(self._labels); cur = self._current
        # 現在ページの前後を先読みしておき、スワイプ時に即表示できるようにする
        load_lo, load_hi = max(0, cur - 2), min(n - 1, cur + 2)
        keep_lo, keep_hi = max(0, cur - 4), min(n - 1, cur + 4)
        w = self._page_width()
        for i in range(load_lo, load_hi + 1):
            if i not in self._loaded:
                self._load_page(i, w)
        # 保持範囲外は解放してメモリを抑える（高さは維持）
        for i in list(self._loaded.keys()):
            if i < keep_lo or i > keep_hi:
                lb = self._labels[i]; h = lb.height()
                lb.setPixmap(QPixmap()); lb.setText("…"); lb.setFixedHeight(h)
                del self._loaded[i]

    def _load_page(self, i: int, w: int):
        self._loaded[i] = True
        try:
            px = bytes_to_pixmap(self._source.read(i))
        except Exception:
            return
        if px.isNull():
            return
        # 高さ合わせ：ページ全体が1画面に収まるよう縮小（横幅も超えないように）
        vh = self._page_height()
        s = px.scaled(self._page_width(), vh, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        lb = self._labels[i]
        lb.setText(""); lb.setPixmap(s); lb.setFixedHeight(vh)

    def jump_to(self, idx: int, animate: bool = False):
        if not (0 <= idx < len(self._labels)): return
        self._current = idx
        y = self._labels[idx].y()
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self.verticalScrollBar().value())
            self._anim.setEndValue(y)
            self._anim.start()
        else:
            self._anim.stop()
            self.verticalScrollBar().setValue(y)
        # ジャンプ時は現在ページを明示的に通知（HUD 更新のため）
        self.page_changed.emit(idx)
        self._update_visible()

    def step(self, direction: int):
        self.jump_to(max(0, min(self._current + direction, len(self._labels) - 1)), animate=True)

    def current_page(self) -> int:
        return self._current

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._labels: return
        ph = self._page_height()
        # サイズが変わるので読み込み済みも一旦解放（プレースホルダ＝1画面高に戻す）
        for i, lb in enumerate(self._labels):
            lb.setPixmap(QPixmap()); lb.setText("…"); lb.setFixedHeight(ph)
        self._loaded = {}
        self._load_timer.start(60)


class ReaderView(QWidget):
    back_requested = Signal()
    bookmark_changed = Signal(str, list)   # (book_id, bookmarks)
    view_changed = Signal(str, dict)       # (book_id, 表示設定) 本ごとに保存

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.source: PageSource | None = None
        self.current_index = 0
        self.rtl_mode = True; self.spread_mode = True; self.spread_offset = 1
        self.fit_mode = "height"        # "height"/"width"
        self.webtoon_mode = False       # 縦読み連続スクロール
        self.book_id: str = ""
        self._bookmarks: list[int] = []
        self._drag_start: QPoint | None = None; self._dragging = False
        self._last_pos: QPoint | None = None    # パンの増分計算用
        self._gesture: str | None = None        # "swipe"/"pan"/"zoom"
        self._zoom_base: float = 1.0            # ズームドラッグ開始時の倍率
        # ズーム中の中央クリックは、ダブルクリック(=等倍に戻す)と区別するため遅延実行する
        self._pending_hud_timer = QTimer(self)
        self._pending_hud_timer.setSingleShot(True)
        self._pending_hud_timer.timeout.connect(self._toggle_hud)
        self._next_px: QPixmap = QPixmap()
        self._prev_px: QPixmap = QPixmap()
        self._hud_visible: bool = True
        self._px_cache: dict = {}        # ページpixmapのLRUキャッシュ
        self._px_cache_order: list = []
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("background:#131019;")

        self._display = SwipeDisplay(self)
        self._anim = _AnimPlayer(self._display)   # 動くGIF/WebP/APNGの再生
        self._display.installEventFilter(self)
        # タッチのスワイプを遅延なく拾えるようにする（マウス挙動は不変）
        self._display.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

        self._webtoon = WebtoonView(self)
        self._webtoon.page_changed.connect(self._on_webtoon_page)
        self._webtoon.clicked.connect(self._toggle_hud)   # 画面クリックでHUD切替
        self._webtoon.installEventFilter(self)   # キー操作を ReaderView へ転送
        self._webtoon.hide()

        self._toolbar_w = QWidget(self)
        self._toolbar_w.setFixedHeight(52)
        self._toolbar_w.setStyleSheet("background:rgba(20,20,20,220);border-bottom:1px solid #2b2539;")
        tb = QHBoxLayout(self._toolbar_w)
        tb.setContentsMargins(8, 6, 8, 6); tb.setSpacing(6)

        self._tr = []   # 言語切替で再翻訳する (widget, 原文, 種別) のリスト

        def fb(jp, cb):
            b = FlatBtn(t(jp), h=38, font_size=15); b.set_callback(cb)
            self._tr.append((b, jp, "text")); return b

        def tb_tog(jp, v, cb):
            b = ToggleBtn(t(jp), v, h=38, font_size=14); b.set_callback(cb)
            self._tr.append((b, jp, "text")); return b

        def tip(w, jp):
            w.setToolTip(t(jp)); self._tr.append((w, jp, "tooltip")); return w

        tb.addWidget(fb("← 本棚", self.back_requested.emit)); tb.addSpacing(8)
        tb.addWidget(fb("最後", self._go_last))
        tb.addWidget(fb("次へ", self._go_forward))
        tb.addWidget(fb("前へ", self._go_backward))
        tb.addWidget(fb("最初", self._go_first))
        tb.addSpacing(6)
        self.page_label = QLabel("0 / 0")
        self.page_label.setStyleSheet("color:#aaa;font-size:15px;font-weight:bold;min-width:90px;")
        tb.addWidget(self.page_label)
        self._page_input = QLineEdit()
        self._page_input.setFixedWidth(80)
        self._page_input.setFixedHeight(36)
        self._page_input.setPlaceholderText(t("ページ番号"))
        self._tr.append((self._page_input, "ページ番号", "placeholder"))
        self._page_input.setStyleSheet(
            "QLineEdit{background:#2b2539;color:#ddd;border:1px solid #463d63;"
            "border-radius:10px;padding:0 6px;font-size:13px;}")
        self._page_input.returnPressed.connect(self._on_page_input)
        tb.addWidget(self._page_input)
        tb.addSpacing(6)

        # しおり：現在ページのトグル＋前後ジャンプ＋一覧
        self._bm_btn = fb("🔖", self._toggle_bookmark)
        tip(self._bm_btn, "このページにしおりを追加 / 解除")
        self._bm_prev_btn = fb("◀栞", self._next_bookmark)
        tip(self._bm_prev_btn, "次のしおりへジャンプ")
        self._bm_next_btn = fb("栞▶", self._prev_bookmark)
        tip(self._bm_next_btn, "前のしおりへジャンプ")
        self._bm_list_btn = fb("しおり ▾", self._show_bookmarks_menu)  # 表示は _update_bookmark_ui が上書き
        tip(self._bm_list_btn, "しおり一覧（クリックでジャンプ）")
        tb.addWidget(self._bm_btn); tb.addWidget(self._bm_prev_btn)
        tb.addWidget(self._bm_next_btn); tb.addWidget(self._bm_list_btn)
        self._grid_btn = fb("🗂 目次", self._toggle_grid)
        tip(self._grid_btn, "全ページのサムネイル一覧から選ぶ")
        tb.addWidget(self._grid_btn)
        tb.addStretch()

        self._rtl_btn    = tb_tog("右→左",    True,  self._on_rtl)
        self._spread_btn = tb_tog("見開き",    True,  self._on_spread)
        self._cover_btn  = tb_tog("表紙を単独", True,  self._on_cover_single)
        tip(self._cover_btn, "1ページ目（表紙）を単独表示し、以降を見開きでペアにする")
        self._fit_btn    = FlatBtn(t("フィット: 高さ"), h=38, font_size=14)
        self._fit_btn.set_callback(self._cycle_fit)
        tip(self._fit_btn, "表示の合わせ方（高さ / 幅 / 全体）を切り替え")
        self._webtoon_btn = tb_tog("縦読み",   False, self._on_webtoon)
        tip(self._webtoon_btn, "縦スクロールの連続表示（Webtoon向け）")
        self._wheel_btn  = tb_tog("ホイール送り", self.settings.wheel_mode == "page",
                                  self._on_wheel_mode)
        tip(self._wheel_btn, "マウスホイールでページを送る（OFFで拡大縮小）")
        self._fs_btn     = tb_tog("全画面",    True,  self._on_fullscreen)
        for b in [self._rtl_btn, self._spread_btn, self._cover_btn,
                  self._fit_btn, self._webtoon_btn, self._wheel_btn, self._fs_btn]:
            tb.addWidget(b)

        self._thumb_strip = PageThumbStrip(self)
        self._thumb_strip.setFixedHeight(PageThumbStrip.STRIP_H)
        self._thumb_strip.page_clicked.connect(self._jump_to_page)

        # グリッド目次（全ページのサムネイル一覧オーバーレイ）
        self._grid = PageGridView(self)
        self._grid.page_clicked.connect(self._grid_jump)
        self._grid.closed.connect(self._close_grid)
        self._grid.hide()

        # 操作ヒント（本を開いた直後に数秒だけ表示）
        self._hint = QLabel(t("右クリックでメニュー表示／ Esc または「← 本棚」で戻る"), self)
        self._tr.append((self._hint, "右クリックでメニュー表示／ Esc または「← 本棚」で戻る", "text"))
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            "background:rgba(20,20,20,220);color:#fff;font-size:14px;"
            "border:1px solid #a06cff;border-radius:18px;padding:8px 18px;")
        self._hint.setVisible(False)
        self._hint_timer = QTimer(self); self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._hide_hint)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._set_hud_visible(False)

    def retranslate(self):
        """言語切替時にツールバー等の文言を貼り替える。"""
        for w, jp, kind in self._tr:
            if kind == "text": w.setText(t(jp))
            elif kind == "tooltip": w.setToolTip(t(jp))
            elif kind == "placeholder": w.setPlaceholderText(t(jp))
        self._update_bookmark_ui()   # しおり一覧ボタンの件数つき表示を復元
        self._update_fit_btn()       # フィットボタン（動的ラベル）を再翻訳

    def _flash_hint(self):
        """本を開いた直後、ツールバーとヒントを数秒だけ表示して操作方法を知らせる。"""
        self._toolbar_w.setVisible(True)
        self._toolbar_w.raise_()
        self._hint.adjustSize()
        self._hint.move((self.width() - self._hint.width()) // 2, 70)
        self._hint.setVisible(True)
        self._hint.raise_()
        self._hint_timer.start(3500)

    def _hide_hint(self):
        self._hint.setVisible(False)
        if not self._hud_visible:
            self._toolbar_w.setVisible(False)

    def _toggle_hud(self):
        self._set_hud_visible(not self._hud_visible)

    def _set_hud_visible(self, v: bool):
        self._hud_visible = v
        if v and hasattr(self, "_hint"):   # メニューを開いたらヒントは消す
            self._hint_timer.stop(); self._hint.setVisible(False)
        self._toolbar_w.setVisible(v)
        self._thumb_strip.setVisible(v)
        if v:
            # 縦読み(WebtoonView)の上に HUD を重ねる
            self._toolbar_w.raise_(); self._thumb_strip.raise_()
        if v and self.source:
            # setGeometry を明示的に呼んでビューポートサイズを確定させる
            w, h = self.width(), self.height()
            sh = PageThumbStrip.STRIP_H
            if w > 0 and h > 0:
                self._thumb_strip.setGeometry(0, h - sh, w, sh)
            cnt = 2 if (not self.webtoon_mode and self._is_spread_start(self.current_index)) else 1
            # ソースが変わったときのみ set_source でリセット、それ以外は set_current のみ
            if self._thumb_strip._source is not self.source:
                self._thumb_strip.set_source(self.source, self.current_index, self.rtl_mode, cnt)
            else:
                self._thumb_strip.set_rtl(self.rtl_mode)
                self._thumb_strip.set_current(self.current_index, cnt)
                self._thumb_strip._load_visible()
            self._thumb_strip.set_bookmarks(self._bookmarks)
            # レイアウト確定後に追加ロード（ビューポートサイズが0のケースをカバー）
            QTimer.singleShot(100, self._thumb_strip._load_visible)
            QTimer.singleShot(500, self._thumb_strip._load_visible)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event); return True
        if obj is not self._display: return False
        t = event.type()
        if t == QEvent.Type.Wheel:
            self._zoom_wheel(event.angleDelta().y(), event.position().toPoint()); return True
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
            self._toggle_hud(); return True
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
            return True
        if t == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self._on_double_click(event.position().toPoint()); return True
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._ptr_press(event.position().toPoint()); return True
        if t == QEvent.Type.MouseMove and self._drag_start is not None:
            self._ptr_move(event.position().toPoint()); return True
        if t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self._ptr_release(); return True
        # タッチのスワイプ（1本指）もマウスと同じ処理に流す
        if t == QEvent.Type.TouchBegin:
            p = self._touch_point(event)
            if p is not None: self._ptr_press(p)
            return True
        if t == QEvent.Type.TouchUpdate and self._drag_start is not None:
            p = self._touch_point(event)
            if p is not None: self._ptr_move(p)
            return True
        if t in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            self._ptr_release(); return True
        return False

    @staticmethod
    def _touch_point(event):
        pts = event.points()
        return pts[0].position().toPoint() if pts else None

    def _ptr_press(self, pos):
        self.setFocus()
        self._pending_hud_timer.stop()  # 保留中の中央クリック(HUD)があれば取り消す
        self._drag_start = pos          # 押下位置（スワイプ/ズームの総量基準・固定）
        self._last_pos = pos            # 直近位置（パンの増分用）
        self._dragging = False
        self._gesture = None            # "swipe" / "pan" / "zoom"
        self._zoom_base = self._display.zoom

    def _ptr_move(self, pos):
        if self._drag_start is None: return
        d = pos - self._drag_start
        if not self._dragging and (abs(d.x()) + abs(d.y())) > 8:
            self._dragging = True
            # ドラッグの種類を開始方向で確定（以降この操作中は固定）。
            # ホイールがズーム操作のときは、上下ドラッグはズームせず移動(パン)のみにする。
            wheel_zoom = (getattr(self.settings, "wheel_mode", "zoom") == "zoom") if self.settings else False
            drag_zoom = (getattr(self.settings, "drag_zoom", True) if self.settings else True) and not wheel_zoom
            if drag_zoom and abs(d.y()) > abs(d.x()):
                self._gesture = "zoom"          # 縦ドラッグ＝無段階ズーム
            elif self._display.zoom > 1.0:
                self._gesture = "pan"           # ズーム中のドラッグ＝移動(パン)
            else:
                self._gesture = "swipe"         # 等倍の横ドラッグ＝ページ送り
        if not self._dragging: return
        if self._gesture == "zoom":
            # 上方向(dyマイナス)で拡大・下方向で縮小。250pxで2倍の無段階ズーム。
            # 押下した位置（マウスポインタ）を固定点にして拡大縮小する。
            dy = pos.y() - self._drag_start.y()
            new_z = self._zoom_base * (2.0 ** (-dy / 250.0))
            self._display.zoom_at(new_z, self._drag_start.x(), self._drag_start.y())
        elif self._gesture == "pan":
            self._display.pan(pos.x() - self._last_pos.x(), pos.y() - self._last_pos.y())
        else:   # swipe
            self._display.set_offset(pos.x() - self._drag_start.x())
            self._update_swipe_adj(pos.x() - self._drag_start.x())
        self._last_pos = pos

    def _ptr_release(self):
        if self._drag_start is not None:
            if self._gesture == "swipe":
                dx = round(self._display._offset)   # ドラッグ中に set_offset 済み
                vw = self._display.width()
                if abs(dx) >= vw // 6:
                    tidx = self._swipe_target_idx(dx < 0)
                    if tidx < 0:
                        self._display.animate_to(0, duration=160)
                    else:
                        target = -vw if dx < 0 else vw
                        def _done(ti=tidx):
                            self.current_index = ti; self._show_current()
                        self._display.animate_to(target, _done, duration=200)
                else:
                    self._display.animate_to(0, duration=160)
            elif not self._dragging:
                x = self._drag_start.x(); w3 = self._display.width() / 3
                if x < w3: self._go_prev_animated()
                elif x > w3 * 2: self._go_next_animated()
                elif self._display.zoom > 1.0:
                    # ズーム中の中央クリックはダブルクリック(等倍に戻す)と区別するため遅延
                    self._pending_hud_timer.start(QApplication.doubleClickInterval())
                else:
                    self._toggle_hud()
        self._drag_start = None; self._last_pos = None
        self._dragging = False; self._gesture = None

    def _on_double_click(self, pos):
        """ズーム中に中央(HUD領域)をダブルクリック → 等倍に戻す（HUDは出さない）。"""
        self._pending_hud_timer.stop()   # 保留中の中央クリック(HUD)を取り消す
        if self._display.zoom > 1.0:
            w3 = self._display.width() / 3
            if w3 <= pos.x() <= w3 * 2:
                self._display.set_zoom(1.0)   # 等倍に戻す（HUDは開かない）

    def _swipe_target_idx(self, left: bool) -> int:
        if not self.source: return -1
        pos = self._spread_positions() if self.spread_mode else list(range(len(self.source)))
        try:
            i = pos.index(self.current_index)
        except ValueError:
            # current_index がスプレッド位置にない場合はスナップして再試行
            self._snap_index()
            try: i = pos.index(self.current_index)
            except ValueError: return -1
        ni = (i - 1 if self.rtl_mode else i + 1) if left else (i + 1 if self.rtl_mode else i - 1)
        return pos[ni] if 0 <= ni < len(pos) else -1

    def _on_wheel_mode(self, v: bool):
        self.settings.wheel_mode = "page" if v else "zoom"
        self.settings.save()

    def _zoom_wheel(self, delta: int, pos=None):
        # 設定で「ページ送り」が選ばれていれば、ホイールでページを送る
        # （下スクロール=次のページ / 上スクロール=前のページ）
        if getattr(self.settings, "wheel_mode", "zoom") == "page":
            if delta < 0: self._go_prev_animated()
            elif delta > 0: self._go_next_animated()
            return
        # 幅合わせのときはホイールで縦スクロール（ズームではなく）
        if self.fit_mode == "width":
            self._display.scroll_v(delta); return
        old = self._display.zoom
        new_z = min(8.0, old * 1.15) if delta > 0 else max(1.0, old / 1.15)
        if abs(old - new_z) < 0.0001: return
        # マウスポインタ位置を中心にズーム（無ければ画面中央）
        if pos is None:
            self._display.zoom_at(new_z, self._display.width() // 2, self._display.height() // 2)
        else:
            self._display.zoom_at(new_z, pos.x(), pos.y())

    def _on_fullscreen(self, v: bool):
        # 全画面の出入りは MainWindow に一元化（アニメ・タイトルバー制御込み）
        win = self.window()
        if v:
            win.enter_fullscreen()
        else:
            win.exit_fullscreen()

    def _exit_fullscreen(self):
        self.window().exit_fullscreen()

    def _on_rtl(self, v: bool):
        self._finish_current_anim()
        self.rtl_mode = v
        if self._hud_visible:
            self._thumb_strip.set_rtl(v)
        self._show_current(); self._save_view()

    def _on_spread(self, v: bool):
        self._finish_current_anim()
        self.spread_mode = v; self._cover_btn.setEnabled(v)
        if v: self._snap_index()
        self._show_current(); self._save_view()

    def _on_cover_single(self, v: bool):
        self._set_offset(1 if v else 0)

    def _set_offset(self, o: int):
        self._finish_current_anim()
        self.spread_offset = o
        self._cover_btn.set_checked(o == 1, silent=True)
        if self.spread_mode: self._snap_index()
        self._show_current(); self._save_view()

    def _save_view(self):
        """現在の表示設定を本ごとに保存（MainWindow 経由で library へ）。"""
        if self.book_id:
            self.view_changed.emit(self.book_id, {
                "rtl": self.rtl_mode, "spread": self.spread_mode,
                "offset": self.spread_offset, "fit": self.fit_mode,
                "webtoon": self.webtoon_mode})

    def _apply_view(self, view: dict):
        """保存済みの表示設定をボタンに反映（コールバックは抑制）。"""
        self.rtl_mode = view.get("rtl", True)
        self.spread_mode = view.get("spread", True)
        self.spread_offset = view.get("offset", 1)
        self.fit_mode = view.get("fit", "height")
        if self.fit_mode not in ("height", "width", "contain"):
            self.fit_mode = "height"
        self.webtoon_mode = bool(view.get("webtoon", False))
        self._rtl_btn.set_checked(self.rtl_mode, silent=True)
        self._spread_btn.set_checked(self.spread_mode, silent=True)
        self._cover_btn.set_checked(self.spread_offset == 1, silent=True)
        self._update_fit_btn()
        self._webtoon_btn.set_checked(self.webtoon_mode, silent=True)
        spread_enabled = self.spread_mode and not self.webtoon_mode
        self._cover_btn.setEnabled(spread_enabled)

    _FIT_ORDER = ("height", "width", "contain")
    _FIT_LABELS = {"height": "高さ", "width": "幅", "contain": "全体"}

    def _cycle_fit(self, *_):
        i = self._FIT_ORDER.index(self.fit_mode) if self.fit_mode in self._FIT_ORDER else 0
        self.fit_mode = self._FIT_ORDER[(i + 1) % len(self._FIT_ORDER)]
        self._update_fit_btn()
        if not self.webtoon_mode:
            self._display.set_fit(self.fit_mode)
        self._save_view()

    def _update_fit_btn(self):
        self._fit_btn.setText(t("フィット: ") + t(self._FIT_LABELS.get(self.fit_mode, "高さ")))

    def _on_webtoon(self, v: bool):
        self.webtoon_mode = v
        if v: self._enter_webtoon()
        else: self._exit_webtoon()
        self._save_view()

    def _enter_webtoon(self):
        for b in (self._spread_btn, self._cover_btn, self._rtl_btn, self._fit_btn):
            b.setEnabled(False)
        self._display.hide()
        self._webtoon.setGeometry(0, 0, self.width(), self.height())
        self._webtoon.show()
        self._toolbar_w.raise_(); self._thumb_strip.raise_()
        self._webtoon.set_source(self.source, self.current_index)
        self._sync_hud()

    def _exit_webtoon(self):
        for b in (self._spread_btn, self._rtl_btn, self._fit_btn):
            b.setEnabled(True)
        self._cover_btn.setEnabled(self.spread_mode)
        self._webtoon.hide(); self._display.show()
        self._display.set_fit(self.fit_mode)
        self._show_current()

    def _on_webtoon_page(self, idx: int):
        self.current_index = idx
        self._sync_hud()

    def _snap_index(self):
        pos = self._spread_positions()
        if pos: self.current_index = min(pos, key=lambda p: abs(p - self.current_index))

    def _spread_positions(self) -> list[int]:
        if not self.source: return []
        total = len(self.source); result = []; i = 0
        if self.spread_offset == 1: result.append(0); i = 1
        while i < total:
            result.append(i); i += 2 if i + 1 < total else 1
        return result

    def _is_spread_start(self, idx: int) -> bool:
        if not self.spread_mode or not self.source: return False
        if self.spread_offset == 1 and idx == 0: return False
        return idx % 2 == self.spread_offset and idx + 1 < len(self.source)

    def load_book(self, book: dict, source: PageSource, start_page: int = -1):
        self._anim.stop()        # 別の本のアニメ再生を止める
        self.book_id = book["id"]; self.source = source
        self._bookmarks = sorted(int(p) for p in book.get("bookmarks", []))
        self._clear_px_cache()   # 別の本のページが残らないようにクリア
        view = book.get("view") or {}
        self._apply_view(view)   # 本ごとの表示設定を反映
        # 初回（綴じ方向が未保存）はソースのメタデータから右綴じ/左綴じを自動判定。
        # 一度保存すれば次回以降はユーザーの設定が優先される（自動判定は再実行しない）。
        if "rtl" not in view and source.direction in ("rtl", "ltr"):
            self.rtl_mode = (source.direction == "rtl")
            self._rtl_btn.set_checked(self.rtl_mode, silent=True)
            self._save_view()
        page = start_page if start_page >= 0 else book.get("last_page", 0)
        self.current_index = min(page, max(0, len(source) - 1))
        if self.spread_mode and not self.webtoon_mode: self._snap_index()
        # 新しい本を開くとき strip をリセット（次の HUD 表示で set_source が走る）
        self._thumb_strip._source = None
        if self.webtoon_mode:
            self._enter_webtoon()
        else:
            self._webtoon.hide(); self._display.show()
            self._display.set_fit(self.fit_mode)
            self._show_current()
        self._set_hud_visible(False)
        # 全画面へは自動移行しない。ボタンは現在のウィンドウ状態に合わせる。
        self._fs_btn.set_checked(getattr(self.window(), "_fullscreen", False), silent=True)
        self._wheel_btn.set_checked(self.settings.wheel_mode == "page", silent=True)
        QTimer.singleShot(120, self._flash_hint)   # 操作ヒントを一定時間表示

    def _jump_to_page(self, idx: int):
        if not self.source: return
        self.current_index = max(0, min(idx, len(self.source) - 1))
        if self.webtoon_mode:
            self._webtoon.jump_to(self.current_index); self._sync_hud(); return
        if self.spread_mode: self._snap_index()
        self._show_current()

    # ── グリッド目次 ────────────────────────────────────────

    def _toggle_grid(self, *_):
        if self._grid.isVisible():
            self._close_grid()
        else:
            self._open_grid()

    def is_grid_open(self) -> bool:
        return self._grid.isVisible()

    def _open_grid(self):
        if not self.source: return
        self._finish_current_anim()
        # グリッドはツールバーの下に配置（メニューを覆い隠さない）。
        # height() が確定前で 0 を返してもツールバー固定高 52 で必ず下げる。
        tb_h = self._toolbar_w.height() or 52
        self._grid.setGeometry(0, tb_h, self.width(), max(0, self.height() - tb_h))
        self._grid.set_source(self.source, self.current_index, self.rtl_mode, self._bookmarks)
        self._grid.show()
        # 「目次」を再度押して戻れるよう、メニュー（ツールバー）は前面に出したままにする
        self._hud_visible = True
        self._toolbar_w.setVisible(True)
        # 下部サムネ帯はグリッドと重なるので開いている間は隠す
        self._thumb_strip.setVisible(False)
        self._raise_menu_over_grid()
        # グリッドのビューポートは grabGesture によりネイティブ窓になり、show() 直後は
        # 非同期で前面に確定する。イベントループ確定後に再度ツールバーを上げ直して、
        # ネイティブ窓にメニューが覆われる（消えて見える）のを防ぐ。
        QTimer.singleShot(0, self._raise_menu_over_grid)
        self._grid.setFocus()   # ホイールスクロール・Esc を受ける

    def _raise_menu_over_grid(self):
        self._grid.raise_()
        self._toolbar_w.raise_()
        self._toolbar_w.update()

    def _close_grid(self):
        if self._grid.isVisible():
            self._grid.hide()
        # HUD 表示中なら下部サムネ帯を元に戻す
        if self._hud_visible:
            self._thumb_strip.setVisible(True); self._thumb_strip.raise_()
        self.setFocus()

    def _grid_jump(self, idx: int):
        self._close_grid()
        self._jump_to_page(idx)

    # ── しおり ──────────────────────────────────────────────

    def _next_bookmark(self):
        nxt = [p for p in sorted(self._bookmarks) if p > self.current_index]
        if nxt: self._jump_to_page(nxt[0])

    def _prev_bookmark(self):
        prv = [p for p in sorted(self._bookmarks) if p < self.current_index]
        if prv: self._jump_to_page(prv[-1])

    def _is_current_bookmarked(self) -> bool:
        return self.current_index in self._bookmarks

    def _toggle_bookmark(self):
        if not self.source: return
        p = self.current_index
        if p in self._bookmarks:
            self._bookmarks.remove(p)
        else:
            self._bookmarks.append(p)
        self._bookmarks.sort()
        self.bookmark_changed.emit(self.book_id, list(self._bookmarks))
        self._update_bookmark_ui()

    def _update_bookmark_ui(self):
        """しおりボタンの見た目と一覧件数、サムネ帯のしおり表示を更新。"""
        on = self._is_current_bookmarked()
        # トグルボタンは点灯/消灯で状態を示す
        if on:
            self._bm_btn.setStyleSheet(
                "QLabel{background:#ffc107;color:#222;border-radius:10px;padding:0 10px;"
                "font-size:15px;} QLabel:hover{background:#ffcd39;}")
        else:
            self._bm_btn.setStyleSheet(
                "QLabel{background:#2b2539;color:#ccc;border-radius:10px;padding:0 10px;"
                "font-size:15px;} QLabel:hover{background:#393350;}")
        self._bm_list_btn.setText(t("しおり {n} ▾").format(n=len(self._bookmarks))
                                  if self._bookmarks else t("しおり ▾"))
        if self._hud_visible:
            self._thumb_strip.set_bookmarks(self._bookmarks)

    def _show_bookmarks_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#262032;color:#ddd;} "
                           "QMenu::item:selected{background:#a06cff;}")
        if not self._bookmarks:
            act = menu.addAction(t("しおりはありません"))
            act.setEnabled(False)
            menu.exec(self._bm_list_btn.mapToGlobal(self._bm_list_btn.rect().bottomLeft()))
            return
        jump_acts = {}
        for p in self._bookmarks:
            a = menu.addAction(t("📑  {n} ページ").format(n=p + 1))
            jump_acts[a] = p
        menu.addSeparator()
        clear_act = menu.addAction(t("すべてのしおりを削除"))
        chosen = menu.exec(self._bm_list_btn.mapToGlobal(self._bm_list_btn.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is clear_act:
            self._bookmarks = []
            self.bookmark_changed.emit(self.book_id, [])
            self._update_bookmark_ui()
        elif chosen in jump_acts:
            self._jump_to_page(jump_acts[chosen])

    def _go_forward(self):
        """ページ番号が増える方向（次のページ）へ進む。RTL/LTR 両対応。"""
        if self.webtoon_mode:
            self._webtoon.step(1); return
        if self.rtl_mode:
            self._go_prev_animated()   # RTL では prev_animated が高インデックス方向
        else:
            self._go_next_animated()   # LTR では next_animated が高インデックス方向

    def _go_backward(self):
        """ページ番号が減る方向（前のページ）へ戻る。RTL/LTR 両対応。"""
        if self.webtoon_mode:
            self._webtoon.step(-1); return
        if self.rtl_mode:
            self._go_next_animated()   # RTL では next_animated が低インデックス方向
        else:
            self._go_prev_animated()   # LTR では prev_animated が低インデックス方向

    def _go_first(self):
        self.current_index = 0
        if self.webtoon_mode:
            self._webtoon.jump_to(0); self._sync_hud(); return
        if self.spread_mode: self._snap_index()
        self._show_current()

    def _go_last(self):
        if not self.source: return
        self.current_index = len(self.source) - 1
        if self.webtoon_mode:
            self._webtoon.jump_to(self.current_index); self._sync_hud(); return
        if self.spread_mode: self._snap_index()
        self._show_current()

    def _on_page_input(self):
        if not self.source: return
        try:
            n = int(self._page_input.text()) - 1
            self._jump_to_page(n)
        except ValueError:
            pass
        self._page_input.clear()
        self.setFocus()

    def _load_page_px(self, idx: int) -> QPixmap:
        if not self.source or idx < 0 or idx >= len(self.source): return QPixmap()
        # デコード済みページをLRUキャッシュ（連続ページ送り・往復を高速化）
        key = (idx, self.spread_mode, self.spread_offset, self.rtl_mode)
        cached = self._px_cache.get(key)
        if cached is not None:
            return cached
        # 画面より大きいJPEGは表示高さに合わせて低解像度デコード（連続めくり高速化）
        target_h = self._display.height()
        try:
            if self._is_spread_start(idx):
                px = combine_spread(self.source.read(idx), self.source.read(idx + 1),
                                    self.rtl_mode, target_h)
            else:
                px = bytes_to_pixmap(self.source.read(idx), target_h)
        except Exception:
            return QPixmap()
        self._px_cache[key] = px
        self._px_cache_order.append(key)
        if len(self._px_cache_order) > 10:   # 最大10枚保持（前後の往復で再デコードしにくく）
            old = self._px_cache_order.pop(0)
            self._px_cache.pop(old, None)
        return px

    def _clear_px_cache(self):
        self._px_cache.clear(); self._px_cache_order.clear()

    def next_page(self):
        if not self.source: return
        if self.spread_mode:
            pos = self._spread_positions()
            try: i = pos.index(self.current_index)
            except ValueError: self._snap_index(); return
            if self.rtl_mode:
                if i > 0: self.current_index = pos[i - 1]; self._show_current()
            else:
                if i < len(pos) - 1: self.current_index = pos[i + 1]; self._show_current()
        else:
            if self.rtl_mode:
                if self.current_index > 0: self.current_index -= 1; self._show_current()
            else:
                if self.current_index < len(self.source) - 1: self.current_index += 1; self._show_current()

    def prev_page(self):
        if not self.source: return
        if self.spread_mode:
            pos = self._spread_positions()
            try: i = pos.index(self.current_index)
            except ValueError: self._snap_index(); return
            if self.rtl_mode:
                if i < len(pos) - 1: self.current_index = pos[i + 1]; self._show_current()
            else:
                if i > 0: self.current_index = pos[i - 1]; self._show_current()
        else:
            if self.rtl_mode:
                if self.current_index < len(self.source) - 1: self.current_index += 1; self._show_current()
            else:
                if self.current_index > 0: self.current_index -= 1; self._show_current()

    def _sync_hud(self):
        """ページ番号・しおり・サムネ帯の現在位置を更新（描画は行わない）。"""
        if not self.source: return
        total = len(self.source); idx = self.current_index
        if not self.webtoon_mode and self._is_spread_start(idx):
            txt = f"{idx + 1}–{idx + 2} / {total}"
        else:
            txt = f"{idx + 1} / {total}"
        self.page_label.setText(txt)
        self._update_bookmark_ui()
        if self._hud_visible:
            cnt = 2 if (not self.webtoon_mode and self._is_spread_start(idx)) else 1
            self._thumb_strip.set_current(idx, cnt)

    def _show_current(self):
        if not self.source: return
        self._anim.stop()   # 前ページのアニメ再生を止める
        if self.webtoon_mode:
            self._sync_hud(); return
        # 現在ページを即座にデコードして表示（隣接ページの先読みは後回し）
        cur = self._load_page_px(self.current_index)
        self._display.set_current(cur, QPixmap(), -1)
        self._display.set_fit(self.fit_mode)
        self._sync_hud()
        # 隣接ページの先読みは描画後に遅延実行（ページ送りの体感を軽くする）
        QTimer.singleShot(0, self._prefetch_adjacent)
        # 動くGIF/WebP/APNGなら再生開始（静止画なら何も起きない）
        QTimer.singleShot(0, self._maybe_animate)

    def _maybe_animate(self):
        """現在ページがアニメーション画像なら再生する（単ページ表示時のみ）。"""
        if not self.source or self.webtoon_mode:
            return
        if self.spread_mode and self._is_spread_start(self.current_index):
            return   # 見開き合成中はアニメ非対応
        if self.source.ext(self.current_index) not in (".gif", ".webp", ".png", ".apng"):
            return   # jpg等で無駄に読み込まない
        try:
            data = self.source.read(self.current_index)
        except Exception:
            return
        self._anim.start(data)

    def _prefetch_adjacent(self):
        if not self.source: return
        pos = self._spread_positions() if self.spread_mode else list(range(len(self.source)))
        try:
            i = pos.index(self.current_index)
        except ValueError:
            self._snap_index()
            pos = self._spread_positions() if self.spread_mode else list(range(len(self.source)))
            try: i = pos.index(self.current_index)
            except ValueError: return
        if self.rtl_mode:
            next_idx = pos[i - 1] if i > 0 else -1
            prev_idx = pos[i + 1] if i < len(pos) - 1 else -1
        else:
            next_idx = pos[i + 1] if i < len(pos) - 1 else -1
            prev_idx = pos[i - 1] if i > 0 else -1
        self._next_px = self._load_page_px(next_idx)
        self._prev_px = self._load_page_px(prev_idx)
        # 現在の adj をプリフェッチ済みのものに更新（アニメーション準備）
        self._display._adj = self._next_px

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._display.setGeometry(0, 0, w, h)
        self._webtoon.setGeometry(0, 0, w, h)
        self._toolbar_w.setGeometry(0, 0, w, 52)
        self._thumb_strip.setGeometry(0, h - PageThumbStrip.STRIP_H, w, PageThumbStrip.STRIP_H)
        self._toolbar_w.raise_()
        self._thumb_strip.raise_()
        if self._grid.isVisible():
            tb_h = self._toolbar_w.height()
            self._grid.setGeometry(0, tb_h, w, max(0, h - tb_h))
            self._grid.raise_()
            self._toolbar_w.raise_()   # メニューは常に最前面
        if self.source and not self.webtoon_mode and not self._display._timer.isActive():
            self._show_current()

    def hideEvent(self, event):
        # 本棚へ戻る等で非表示になったらアニメ再生を止める（CPU節約）
        self._anim.stop()
        super().hideEvent(event)

    def _shortcut_map(self) -> dict:
        if self.settings is not None and getattr(self.settings, "shortcuts", None):
            return self.settings.shortcuts
        return DEFAULT_SHORTCUTS

    def keyPressEvent(self, event):
        s = QKeySequence(event.key()).toString()
        sc = self._shortcut_map()

        def hit(action: str) -> bool:
            return bool(s) and s in sc.get(action, [])

        # 縦読み中のページ送り（S・↓・A・←＝次／W・↑・D・→＝前）
        if self.webtoon_mode:
            k = event.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_S, Qt.Key.Key_Left, Qt.Key.Key_A):
                self._webtoon.step(1); return
            if k in (Qt.Key.Key_Up, Qt.Key.Key_W, Qt.Key.Key_Right, Qt.Key.Key_D):
                self._webtoon.step(-1); return

        if hit("next_page"): self._go_next_animated()
        elif hit("prev_page"): self._go_prev_animated()
        elif hit("first_page"): self._go_first()
        elif hit("last_page"): self._go_last()
        elif hit("bookmark"): self._toggle_bookmark()
        elif hit("next_bookmark"): self._next_bookmark()
        elif hit("prev_bookmark"): self._prev_bookmark()
        elif hit("toggle_menu"): self._toggle_hud()
        elif hit("fullscreen"):
            self.window().toggle_fullscreen()
        elif hit("back"):
            # 漫画閲覧中の Esc /「戻る」は常に本棚へ。
            # 全画面の解除は _back_to_library 側でまとめて行う。
            self.back_requested.emit()
        else: super().keyPressEvent(event)

    def _finish_current_anim(self):
        """進行中のアニメーションを即座に完了させる"""
        if self._display._timer.isActive():
            self._display._timer.stop()
            self._display._offset = float(self._display._anim_target)
            if self._display._anim_cb:
                cb = self._display._anim_cb
                self._display._anim_cb = None
                cb()

    def _go_next_animated(self):
        if not self.source: return
        if self.webtoon_mode: self._webtoon.step(1); return
        self._finish_current_anim()
        tidx = self._swipe_target_idx(True)
        if tidx < 0: return
        # 先読み未完了なら即座にロード（スライド中の隣ページを確実に表示）
        if self._next_px.isNull():
            self._next_px = self._load_page_px(tidx)
        self._display._adj = self._next_px; self._display._adj_dir = -1
        vw = self._display.width()
        def _done(t=tidx): self.current_index = t; self._show_current()
        self._display.animate_to(-vw, _done, duration=200)

    def _go_prev_animated(self):
        if not self.source: return
        if self.webtoon_mode: self._webtoon.step(-1); return
        self._finish_current_anim()
        tidx = self._swipe_target_idx(False)
        if tidx < 0: return
        if self._prev_px.isNull():
            self._prev_px = self._load_page_px(tidx)
        self._display._adj = self._prev_px; self._display._adj_dir = 1
        vw = self._display.width()
        def _done(t=tidx): self.current_index = t; self._show_current()
        self._display.animate_to(vw, _done, duration=200)

    def _update_swipe_adj(self, dx: int):
        if dx < 0:
            self._display._adj = self._next_px; self._display._adj_dir = -1
        else:
            self._display._adj = self._prev_px; self._display._adj_dir = 1

    def get_current_page(self) -> int: return self.current_index
    def get_total_pages(self) -> int: return len(self.source) if self.source else 0
