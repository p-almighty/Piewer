import io

from PySide6.QtCore import Signal, QRunnable, QObject
from PySide6.QtGui import QPixmap, QImage
from PIL import Image

from config import (PageSource, current_covers_dir, COVER_GEN_W, COVER_GEN_H,
                    COVER_EXT, COVER_JPG_QUALITY, READ_DECODE_ZOOM_HEADROOM)

Image.MAX_IMAGE_PIXELS = None


def _draft_decode(img: Image.Image, target_h: int) -> None:
    """表示高さ(target_h)にズーム余裕を掛けた高さまで JPEG を低解像度デコードする。

    PIL の draft は「要求サイズ以上の最小サイズ」にしか縮小しないため、
    READ_DECODE_ZOOM_HEADROOM 倍までのズームでは画質が落ちない。JPEG以外や
    既に十分小さい画像では何もしない（draft 自体が非対応形式では no-op）。
    """
    if target_h <= 0 or READ_DECODE_ZOOM_HEADROOM <= 0:
        return
    h = img.height
    if h <= 0:
        return
    want = int(target_h * READ_DECODE_ZOOM_HEADROOM)
    if h <= want:
        return   # すでに十分小さい
    try:
        img.draft("RGB", (max(1, int(img.width * want / h)), want))
    except Exception:
        pass


def apply_exif(img: Image.Image) -> Image.Image:
    try:
        ori = img.getexif().get(274, 1)
    except Exception:
        return img
    if ori == 1: return img
    img = img.convert("RGB")
    ops = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
           4: Image.Transpose.FLIP_TOP_BOTTOM,  5: Image.Transpose.TRANSPOSE,
           6: Image.Transpose.ROTATE_270,        7: Image.Transpose.TRANSVERSE,
           8: Image.Transpose.ROTATE_90}
    try:
        if ori in ops: img = img.transpose(ops[ori])
    except Exception:
        pass
    return img


def _pil_to_pixmap(img: Image.Image) -> QPixmap:
    img = apply_exif(img); img = img.convert("RGB")
    raw = img.tobytes()
    # raw はこの関数スコープで生存しており、fromImage がピクスマップ側へコピーするため
    # 中間の QImage.copy() は不要（1ページあたり画像1枚分のメモリコピーを削減）。
    qimg = QImage(raw, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def bytes_to_pixmap(data: bytes, target_h: int = 0) -> QPixmap:
    img = Image.open(io.BytesIO(data))
    _draft_decode(img, target_h)   # 画面より大きいJPEGは低解像度デコードして高速化
    return _pil_to_pixmap(img)


def make_cover_image(data: bytes) -> QImage:
    img = Image.open(io.BytesIO(data))
    img = apply_exif(img); img = img.convert("RGB")
    img.thumbnail((COVER_GEN_W, COVER_GEN_H), Image.LANCZOS)
    raw = img.tobytes()
    return QImage(raw, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()


def combine_spread(da: bytes, db: bytes, rtl: bool, target_h: int = 0) -> QPixmap:
    def load(d: bytes) -> Image.Image:
        im = Image.open(io.BytesIO(d))
        _draft_decode(im, target_h)   # 見開きは横2枚ぶん重いので各ページを低解像度デコード
        return apply_exif(im).convert("RGB")
    ia, ib = load(da), load(db)
    h = max(ia.height, ib.height)
    if ia.height != h: ia = ia.resize((int(ia.width * h / ia.height), h), Image.LANCZOS)
    if ib.height != h: ib = ib.resize((int(ib.width * h / ib.height), h), Image.LANCZOS)
    left, right = (ib, ia) if rtl else (ia, ib)
    canvas = Image.new("RGB", (left.width + right.width, h), (0, 0, 0))
    canvas.paste(left, (0, 0)); canvas.paste(right, (left.width, 0))
    return _pil_to_pixmap(canvas)


class CoverWorkerSignals(QObject):
    finished = Signal(str, QImage)


class CoverWorker(QRunnable):
    def __init__(self, book: dict):
        super().__init__()
        self.book = book; self.signals = CoverWorkerSignals()

    def run(self):
        book = self.book
        from pathlib import Path
        cp = Path(book["cover_cache"]) if book["cover_cache"] else None
        if cp and cp.exists():
            self.signals.finished.emit(book["id"], QImage(str(cp))); return
        try:
            src = PageSource(book["path"])
            if not src: self.signals.finished.emit(book["id"], QImage()); return
            img = make_cover_image(src.read_first())
            sp = current_covers_dir() / f"{book['id']}.{COVER_EXT}"
            img.save(str(sp), "JPG", COVER_JPG_QUALITY)
            self.signals.finished.emit(book["id"], img)
        except Exception:
            self.signals.finished.emit(book["id"], QImage())


class _ThumbSignals(QObject):
    # QImageはスレッド間マーシャリングで問題が起きやすいため bytes + 寸法で渡す
    done = Signal(int, bytes, int, int)  # idx, raw_rgb888, width, height


class _ThumbWorker(QRunnable):
    def __init__(self, source, idx: int):
        super().__init__(); self.source = source; self.idx = idx
        self.signals = _ThumbSignals()

    def run(self):
        try:
            data = self.source.read(self.idx)
            img = apply_exif(Image.open(io.BytesIO(data))).convert("RGB")
            img.thumbnail((66, 88), Image.LANCZOS)
            self.signals.done.emit(self.idx, img.tobytes(), img.width, img.height)
        except Exception:
            import traceback, sys
            print(f"[_ThumbWorker] idx={self.idx} で例外発生:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self.signals.done.emit(self.idx, b"", 0, 0)
