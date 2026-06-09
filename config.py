import json
import re
import zipfile
import posixpath
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

import i18n

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    RAR_SUPPORT = False

try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# PDFのレンダリング解像度倍率（高いほど高画質・低速）
PDF_ZOOM = 2.0

# リーダーのページデコード時、画面より大きいJPEGを「表示高さ×この倍率」まで
# 低解像度デコード(PIL draft)して連続めくりを高速化する。draftは要求サイズ以上の
# 最小サイズにしか落とさないため、この倍率までのズームは画質が劣化しない。
# 値を下げるほど高速（普通サイズのスキャンも縮小される）がズームが甘くなる。
# 1.5=バランス / 2.0=画質優先 / 1.0=軽さ優先。0以下で無効。
READ_DECODE_ZOOM_HEADROOM = 1.5

APP_DIR            = Path.home() / ".manga_viewer"
DEFAULT_COVERS_DIR = APP_DIR / "covers"
LIBRARY_FILE       = APP_DIR / "library.json"
SETTINGS_FILE      = APP_DIR / "settings.json"

# カバー画像の保存先（ユーザーが変更可能）。set_covers_dir で切り替える。
_covers_dir = DEFAULT_COVERS_DIR


def current_covers_dir() -> Path:
    """現在有効なカバー保存先を返す。"""
    return _covers_dir


def set_covers_dir(path: str | None) -> Path:
    """カバー保存先を切り替える。空/Noneならデフォルトに戻す。作成に失敗したらデフォルト。"""
    global _covers_dir
    target = Path(path) if path else DEFAULT_COVERS_DIR
    try:
        target.mkdir(parents=True, exist_ok=True)
        _covers_dir = target
    except Exception:
        _covers_dir = DEFAULT_COVERS_DIR
        _covers_dir.mkdir(parents=True, exist_ok=True)
    return _covers_dir
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
COVER_GEN_W, COVER_GEN_H = 210, 290
CARD_SPACING = 16
APP_NAME = "Piewer"
APP_VERSION = "1.72"
# 完全無料・オープンソース。登録数の制限はなし。寄付（任意）の受け口。
SUPPORT_URL = "https://ko-fi.com/p_almighty"   # 寄付（Ko-fi）。後で差し替え可
# 履歴棚（最近読んだ本）
HISTORY_ID = "__history__"
HISTORY_NAME = "最近読んだ本"
HISTORY_MAX = 100
# お気に入り棚（★を付けた本だけを集めた仮想本棚）
FAVORITES_ID = "__favorites__"
FAVORITES_NAME = "お気に入り"
# 最近追加した本（追加日が新しい順）
RECENT_ID = "__recent__"
RECENT_NAME = "最近追加した本"
RECENT_MAX = 100
# 続きを読む（読みかけ＝進捗あり・未読了）
CONTINUE_ID = "__continue__"
CONTINUE_NAME = "続きを読む"
# 仮想本棚（実体を持たず、条件で本を集める棚）のID一覧
VIRTUAL_SHELF_IDS = (HISTORY_ID, FAVORITES_ID, RECENT_ID, CONTINUE_ID)
# 表紙キャッシュはJPGで保存（PNGより大幅に小容量）
COVER_EXT = "jpg"
COVER_JPG_QUALITY = 88

# キーボードショートカット（リーダー操作）。値は QKeySequence(key).toString() 形式の文字列。
DEFAULT_SHORTCUTS = {
    "next_page":   ["Right", "D", "Up"],
    "prev_page":   ["Left", "A", "Down"],
    "first_page":  ["Home"],
    "last_page":   ["End"],
    "fullscreen":  ["F11"],
    "back":        ["Esc"],
    "bookmark":    ["B"],
    "next_bookmark": ["["],
    "prev_bookmark": ["]"],
    "toggle_menu": ["M"],
}
# 設定ダイアログに表示する操作名（順序もこの通り）
SHORTCUT_LABELS = {
    "next_page":   "次のページ",
    "prev_page":   "前のページ",
    "first_page":  "最初のページ",
    "last_page":   "最後のページ",
    "fullscreen":  "全画面の切り替え",
    "back":        "本棚に戻る",
    "bookmark":    "しおりの追加・解除",
    "next_bookmark": "次のしおりへジャンプ",
    "prev_bookmark": "前のしおりへジャンプ",
    "toggle_menu": "メニュー(HUD)の表示切替",
}


def default_shortcuts() -> dict:
    """ディープコピーした既定ショートカットを返す。"""
    return {k: list(v) for k, v in DEFAULT_SHORTCUTS.items()}

APP_STYLE = """
QToolTip {
    background-color:#2b2539; color:#e8e4f0; border:1px solid #a06cff;
    border-radius:6px; padding:4px 8px; font-size:12px; }
QMessageBox { background-color: #262032; }
QMessageBox QLabel { color: #ddd; font-size: 13px; }
QMessageBox QPushButton {
    background:#322b45; color:#ddd; border:1px solid #463d63;
    border-radius:10px; padding:5px 18px; min-width:70px; font-size:12px; }
QMessageBox QPushButton:hover { background:#423a5a; }
QMessageBox QPushButton:default { background:#a06cff; color:white; border-color:#a06cff; }
QInputDialog { background-color:#262032; }
QInputDialog QLabel { color:#ddd; font-size:13px; }
QInputDialog QLineEdit {
    background:#2b2539; color:#ddd; border:1px solid #463d63;
    border-radius:10px; padding:5px 8px; font-size:12px; }
QInputDialog QPushButton {
    background:#322b45; color:#ddd; border:1px solid #463d63;
    border-radius:10px; padding:5px 18px; min-width:70px; font-size:12px; }
QInputDialog QPushButton:hover { background:#423a5a; }
QInputDialog QPushButton:default { background:#a06cff; color:white; border-color:#a06cff; }
"""


def ensure_dirs():
    APP_DIR.mkdir(exist_ok=True)
    _covers_dir.mkdir(parents=True, exist_ok=True)


def export_backup(path: str):
    """library.json と settings.json をまとめて1ファイルに書き出す。"""
    data = {"app": APP_NAME, "version": APP_VERSION, "library": {}, "settings": {}}
    if LIBRARY_FILE.exists():
        data["library"] = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
    if SETTINGS_FILE.exists():
        data["settings"] = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def import_backup(path: str) -> bool:
    """エクスポートしたバックアップを読み込み library/settings を書き戻す。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "library" not in data and "settings" not in data:
        raise ValueError(i18n.t("バックアップ形式ではありません"))
    APP_DIR.mkdir(exist_ok=True)
    if isinstance(data.get("library"), dict) and data["library"]:
        LIBRARY_FILE.write_text(json.dumps(data["library"], ensure_ascii=False, indent=2),
                                encoding="utf-8")
    if isinstance(data.get("settings"), dict) and data["settings"]:
        SETTINGS_FILE.write_text(json.dumps(data["settings"], ensure_ascii=False),
                                 encoding="utf-8")
    return True


class Settings:
    SIZES = {"small": (110, 150), "medium": (160, 220), "large": (210, 290)}

    def __init__(self):
        self.thumb_size = "medium"
        self.covers_dir = ""        # 空=デフォルト(~/.manga_viewer/covers)
        self.shelf_open_pos = "remember"   # "remember"=前回位置 / "top"=一番上
        self.wheel_mode = "zoom"    # マウスホイール: "zoom"=拡大縮小 / "page"=ページ送り
        self.resume_mode = "continue"  # 本を開いたとき: "continue"=続きから / "ask"=毎回確認 / "start"=最初から
        self.drag_zoom = True       # 上下ドラッグで無段階ズーム（マンガミーヤ式）
        self.browse_path = ""       # フォルダ閲覧で最後に開いていた場所
        self.auto_tag_on_add = False  # 本の追加時にファイル名から自動タグ付け（実験的）
        self.tag_labels = {}          # オートタグ分類名の上書き {役割キー:表示名}（空=既定）
        self.image_fx = {}            # 画質補正/擬似カラー化の設定（空=既定OFF。image_fx.DEFAULT参照）
        self.accent = "violet"        # アクセント色プリセット名
        self.theme = "dark"           # テーマ: "dark" / "light"
        self.lang = ""              # ""=未設定(初回にOSロケールから判定) / "ja" / "en"
        self.shortcuts = default_shortcuts()
        APP_DIR.mkdir(exist_ok=True)
        self._load()
        if self.lang:
            i18n.set_lang(self.lang)
        set_covers_dir(self.covers_dir)   # 設定をカバー保存先に反映
        ensure_dirs()

    def _load(self):
        if SETTINGS_FILE.exists():
            try:
                d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                self.thumb_size = d.get("thumb_size", "medium")
                self.covers_dir = d.get("covers_dir", "")
                if d.get("shelf_open_pos") in ("remember", "top"):
                    self.shelf_open_pos = d["shelf_open_pos"]
                if d.get("wheel_mode") in ("zoom", "page"):
                    self.wheel_mode = d["wheel_mode"]
                if d.get("resume_mode") in ("continue", "ask", "start"):
                    self.resume_mode = d["resume_mode"]
                self.drag_zoom = bool(d.get("drag_zoom", True))
                self.browse_path = str(d.get("browse_path", ""))
                self.auto_tag_on_add = bool(d.get("auto_tag_on_add", False))
                tl = d.get("tag_labels")
                if isinstance(tl, dict):
                    self.tag_labels = {str(k): str(v) for k, v in tl.items() if str(v).strip()}
                fx = d.get("image_fx")
                if isinstance(fx, dict):
                    self.image_fx = fx
                self.accent = str(d.get("accent", "violet"))
                if d.get("theme") in ("dark", "light"):
                    self.theme = d["theme"]
                if d.get("lang") in ("ja", "en"):
                    self.lang = d["lang"]
                sc = d.get("shortcuts")
                if isinstance(sc, dict):
                    # 既知のアクションのみ採用。新規アクションは既定値を維持する。
                    for action in self.shortcuts:
                        keys = sc.get(action)
                        if isinstance(keys, list):
                            self.shortcuts[action] = [str(k) for k in keys]
            except Exception:
                pass

    def save(self):
        SETTINGS_FILE.write_text(
            json.dumps({"thumb_size": self.thumb_size, "covers_dir": self.covers_dir,
                        "shelf_open_pos": self.shelf_open_pos, "lang": self.lang,
                        "wheel_mode": self.wheel_mode, "resume_mode": self.resume_mode,
                        "drag_zoom": self.drag_zoom, "browse_path": self.browse_path,
                        "auto_tag_on_add": self.auto_tag_on_add, "accent": self.accent,
                        "tag_labels": self.tag_labels, "image_fx": self.image_fx,
                        "theme": self.theme,
                        "shortcuts": self.shortcuts},
                       ensure_ascii=False),
            encoding="utf-8")

    def set_shortcut(self, action: str, keys: list[str]):
        if action in self.shortcuts:
            self.shortcuts[action] = list(keys)
            self.save()

    def reset_shortcuts(self):
        self.shortcuts = default_shortcuts(); self.save()

    def effective_tag_labels(self) -> dict:
        """既定の分類名にユーザー設定を重ねた {役割キー:表示名} を返す。"""
        import auto_tag
        lab = dict(auto_tag.DEFAULT_LABELS)
        lab.update({k: v for k, v in self.tag_labels.items()
                    if k in lab and str(v).strip()})
        return lab

    def set_tag_labels(self, labels: dict):
        """分類名の上書きを保存（既定と同じ/空の項目は持たない）。"""
        import auto_tag
        out = {}
        for k, default in auto_tag.DEFAULT_LABELS.items():
            v = str(labels.get(k, "")).strip()
            if v and v != default:
                out[k] = v
        self.tag_labels = out
        self.save()

    def reload(self):
        """ファイルから読み直す（バックアップ復元後などに使用）。"""
        self.thumb_size = "medium"; self.covers_dir = ""
        self.shelf_open_pos = "remember"; self.wheel_mode = "zoom"
        self.resume_mode = "continue"; self.drag_zoom = True
        self.auto_tag_on_add = False
        self.tag_labels = {}; self.image_fx = {}
        self.shortcuts = default_shortcuts()
        self._load(); set_covers_dir(self.covers_dir)

    def set_covers_dir(self, path: str):
        """カバー保存先を設定して永続化。実際に有効化された絶対パスを返す。"""
        applied = set_covers_dir(path)
        self.covers_dir = "" if applied == DEFAULT_COVERS_DIR else str(applied)
        self.save()
        return applied

    @property
    def cover_w(self) -> int: return self.SIZES.get(self.thumb_size, (160, 220))[0]
    @property
    def cover_h(self) -> int: return self.SIZES.get(self.thumb_size, (160, 220))[1]


class Library:
    def __init__(self):
        ensure_dirs()
        self.shelves: list[dict] = []
        self.active_shelf_id: str = ""
        self.history: list[str] = []   # 最近読んだ本のID（新しい順・最大HISTORY_MAX）
        self._path_cache: set[str] = set()
        self.limit: int | None = None  # 登録上限（常にNone＝無制限。完全無料）
        self._load()

    @property
    def total_count(self) -> int:
        return len(self._path_cache)

    def is_full(self) -> bool:
        return False   # 完全無料・無制限

    def remaining(self) -> int | None:
        return None

    def _load(self):
        if LIBRARY_FILE.exists():
            try:
                data = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
                if "shelves" not in data and "books" in data:
                    self.shelves = [{"id": "shelf_default", "name": i18n.t("本棚1"), "books": data["books"]}]
                else:
                    self.shelves = data.get("shelves", [])
                self.active_shelf_id = data.get("active_shelf", "")
                self.history = data.get("history", [])
            except Exception:
                pass
        if not self.shelves:
            self.shelves = [{"id": "shelf_default", "name": i18n.t("本棚1"), "books": []}]
        if (not self.active_shelf_id or
                (self.active_shelf_id not in VIRTUAL_SHELF_IDS and
                 not any(s["id"] == self.active_shelf_id for s in self.shelves))):
            self.active_shelf_id = self.shelves[0]["id"]
        self._rebuild_path_cache()

    def _rebuild_path_cache(self):
        self._path_cache = {b["path"] for s in self.shelves for b in s["books"]}

    def save(self):
        LIBRARY_FILE.write_text(
            json.dumps({"shelves": self.shelves, "active_shelf": self.active_shelf_id,
                        "history": self.history},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 履歴棚 ──────────────────────────────────────────────

    @property
    def is_history_active(self) -> bool:
        return self.active_shelf_id == HISTORY_ID

    @property
    def is_favorites_active(self) -> bool:
        return self.active_shelf_id == FAVORITES_ID

    @property
    def is_virtual_active(self) -> bool:
        return self.active_shelf_id in VIRTUAL_SHELF_IDS

    def favorite_books(self) -> list[dict]:
        """★を付けた本を全本棚から集める（重複IDは最初の1冊）。"""
        seen = set(); result = []
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b.get("favorite") and b["id"] not in seen:
                    seen.add(b["id"]); result.append(b)
        return result

    def unfavorite_many(self, bids: set):
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] in bids:
                    b["favorite"] = False
        self.save()

    @staticmethod
    def is_read(book: dict) -> bool:
        """読了（総ページが分かっていて最終ページ付近まで到達）か。"""
        tp = book.get("total_pages", 0)
        return tp > 0 and book.get("last_page", 0) >= tp - 1

    @staticmethod
    def in_progress(book: dict) -> bool:
        """読みかけ（読み始めていて未読了）か。"""
        return book.get("last_page", 0) > 0 and not Library.is_read(book)

    def _unique_books(self) -> list[dict]:
        seen = set(); out = []
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] not in seen:
                    seen.add(b["id"]); out.append(b)
        return out

    def recent_books(self) -> list[dict]:
        """追加日が新しい順（最大RECENT_MAX件）。"""
        books = [b for b in self._unique_books() if b.get("added_at")]
        books.sort(key=lambda b: b.get("added_at", ""), reverse=True)
        return books[:RECENT_MAX]

    def continue_books(self) -> list[dict]:
        """読みかけの本を、最近開いた順で集める。"""
        books = [b for b in self._unique_books() if self.in_progress(b)]
        books.sort(key=lambda b: b.get("last_opened", ""), reverse=True)
        return books

    def record_history(self, bid: str):
        """本を履歴の先頭へ。重複は除き、最大HISTORY_MAX件に保つ。"""
        self.history = [h for h in self.history if h != bid]
        self.history.insert(0, bid)
        if len(self.history) > HISTORY_MAX:
            self.history = self.history[:HISTORY_MAX]
        self.save()

    def history_books(self) -> list[dict]:
        """履歴順（新しい順）の書籍リスト。削除済みのIDは除外する。"""
        result = []
        for bid in self.history:
            b = self.get(bid)
            if b is not None:
                result.append(b)
        return result

    def remove_from_history(self, bid: str):
        self.history = [h for h in self.history if h != bid]
        self.save()

    def remove_many_from_history(self, bids: set):
        self.history = [h for h in self.history if h not in bids]
        self.save()

    @property
    def current_shelf(self) -> dict:
        if self.active_shelf_id == HISTORY_ID:
            return {"id": HISTORY_ID, "name": HISTORY_NAME, "books": self.history_books()}
        if self.active_shelf_id == FAVORITES_ID:
            return {"id": FAVORITES_ID, "name": FAVORITES_NAME, "books": self.favorite_books()}
        if self.active_shelf_id == RECENT_ID:
            return {"id": RECENT_ID, "name": RECENT_NAME, "books": self.recent_books()}
        if self.active_shelf_id == CONTINUE_ID:
            return {"id": CONTINUE_ID, "name": CONTINUE_NAME, "books": self.continue_books()}
        return next((s for s in self.shelves if s["id"] == self.active_shelf_id), self.shelves[0])

    @property
    def books(self) -> list[dict]:
        return self.current_shelf["books"]

    def switch_shelf(self, sid: str):
        if sid in VIRTUAL_SHELF_IDS or any(s["id"] == sid for s in self.shelves):
            self.active_shelf_id = sid; self.save()

    def reorder_shelf(self, src_id: str, target_id: str | None):
        """src_id の本棚を target_id の直前へ移動。target_id が空/Noneなら末尾へ。"""
        if src_id == target_id: return
        src = next((s for s in self.shelves if s["id"] == src_id), None)
        if not src: return
        self.shelves.remove(src)
        if not target_id:
            self.shelves.append(src)
        else:
            idx = next((i for i, s in enumerate(self.shelves) if s["id"] == target_id),
                       len(self.shelves))
            self.shelves.insert(idx, src)
        self.save()

    def set_shelf_order(self, ids: list[str]):
        """与えられたID順に本棚を並べ替える。リストに無い棚は末尾に残す。"""
        order = {sid: i for i, sid in enumerate(ids)}
        self.shelves.sort(key=lambda s: order.get(s["id"], len(order) + 1))
        self.save()

    def add_shelf(self, name: str) -> dict:
        sid = "shelf_" + hashlib.md5(f"{name}{datetime.now()}".encode()).hexdigest()[:8]
        shelf = {"id": sid, "name": name, "books": []}
        self.shelves.append(shelf); self.save()
        return shelf

    def delete_shelf(self, sid: str):
        if len(self.shelves) <= 1: return
        self.shelves = [s for s in self.shelves if s["id"] != sid]
        if self.active_shelf_id == sid:
            self.active_shelf_id = self.shelves[0]["id"]
        self.save()

    def rename_shelf(self, sid: str, name: str):
        for s in self.shelves:
            if s["id"] == sid: s["name"] = name; break
        self.save()

    def add(self, path: str, save: bool = True) -> dict | None:
        path = str(Path(path).resolve())
        if path in self._path_cache: return None
        bid = hashlib.md5(path.encode()).hexdigest()
        book = {"id": bid, "title": Path(path).stem, "path": path,
                "last_page": 0, "total_pages": 0, "cover_cache": "",
                "added_at": datetime.now().isoformat(), "last_opened": "",
                "bookmarks": [], "favorite": False, "tags": [], "view": {}}
        self.current_shelf["books"].insert(0, book)
        self._path_cache.add(path)
        if save: self.save()
        return book

    def remove(self, bid: str):
        self.current_shelf["books"] = [b for b in self.current_shelf["books"] if b["id"] != bid]
        self._rebuild_path_cache(); self.save()

    def remove_many(self, bids: set):
        self.current_shelf["books"] = [b for b in self.current_shelf["books"] if b["id"] not in bids]
        self._rebuild_path_cache(); self.save()

    def remove_many_everywhere(self, bids: set):
        """全本棚＋履歴から本を削除（仮想棚からの削除＝完全削除に使う）。"""
        for shelf in self.shelves:
            shelf["books"] = [b for b in shelf["books"] if b["id"] not in bids]
        self.history = [h for h in self.history if h not in bids]
        self._rebuild_path_cache(); self.save()

    def update_progress(self, bid: str, page: int, total: int):
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] == bid:
                    b["last_page"] = page; b["total_pages"] = total
                    b["last_opened"] = datetime.now().strftime("%Y/%m/%d")
                    self.save(); return

    def set_read_state(self, bid: str, read: bool):
        """既読/未読を手動で切り替える（既読=last_opened付与・未読=進捗もリセット）。"""
        for b in self._each(bid):
            if read:
                if not b.get("last_opened"):
                    b["last_opened"] = datetime.now().strftime("%Y/%m/%d")
            else:
                b["last_opened"] = ""
                b["last_page"] = 0
        self.save()

    def set_cover(self, bid: str, path: str):
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] == bid: b["cover_cache"] = path; self.save(); return

    def set_view(self, bid: str, view: dict):
        """本ごとの表示設定（右綴じ/見開き/始まり/フィット等）を保存。"""
        for b in self._each(bid):
            b["view"] = dict(view)
        self.save()

    # ── しおり / お気に入り / タグ ───────────────────────────

    def _each(self, bid: str):
        """指定IDの本（全棚にある同一IDを含む）を順に返すジェネレータ。"""
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] == bid:
                    yield b

    def set_bookmarks(self, bid: str, bookmarks: list[int]):
        bm = sorted({int(p) for p in bookmarks})
        for b in self._each(bid):
            b["bookmarks"] = list(bm)
        self.save()

    def set_favorite(self, bid: str, fav: bool):
        for b in self._each(bid):
            b["favorite"] = bool(fav)
        self.save()

    def toggle_favorite(self, bid: str) -> bool:
        b = self.get(bid)
        new = not bool(b.get("favorite", False)) if b else True
        self.set_favorite(bid, new)
        return new

    def set_tags(self, bid: str, tags: list[str]):
        clean = []
        for t in tags:
            t = str(t).strip()
            if t and t not in clean:
                clean.append(t)
        for b in self._each(bid):
            b["tags"] = list(clean)
        self.save()

    def add_tags_bulk(self, mapping: dict) -> int:
        """{book_id: [追加タグ,...]} を既存タグにマージ（消さない）。1回だけ保存。

        変更した書籍数（ユニークID）を返す。自動タグ付けの一括適用に使う。
        """
        changed = set()
        for shelf in self.shelves:
            for b in shelf["books"]:
                add = mapping.get(b["id"])
                if not add:
                    continue
                cur = b.get("tags", [])
                merged = list(cur)
                for t in add:
                    t = str(t).strip()
                    if t and t not in merged:
                        merged.append(t)
                if len(merged) != len(cur):
                    b["tags"] = merged
                    changed.add(b["id"])
        if changed:
            self.save()
        return len(changed)

    def all_tags(self) -> list[str]:
        """登録済みの全タグを重複なくソートして返す。"""
        tags = set()
        for shelf in self.shelves:
            for b in shelf["books"]:
                for t in b.get("tags", []):
                    tags.add(t)
        return sorted(tags)

    def rename_tag(self, old: str, new: str) -> int:
        """全本のタグ old を new に置換。影響した本の数を返す。"""
        new = new.strip()
        if not new or old == new:
            return 0
        n = 0
        for shelf in self.shelves:
            for b in shelf["books"]:
                tags = b.get("tags", [])
                if old in tags:
                    # 重複を避けつつ置換し順序を維持
                    b["tags"] = list(dict.fromkeys(new if t == old else t for t in tags))
                    n += 1
        if n: self.save()
        return n

    def rename_tag_prefix(self, old_pfx: str, new_pfx: str) -> int:
        """「old_pfx:値」形式のタグの接頭辞を new_pfx に一括置換。影響した本の数。"""
        old_pfx = old_pfx.strip(); new_pfx = new_pfx.strip()
        if not old_pfx or not new_pfx or old_pfx == new_pfx:
            return 0
        op = old_pfx + ":"; np = new_pfx + ":"
        n = 0
        for shelf in self.shelves:
            for b in shelf["books"]:
                tags = b.get("tags", [])
                if any(t.startswith(op) for t in tags):
                    b["tags"] = list(dict.fromkeys(
                        (np + t[len(op):]) if t.startswith(op) else t for t in tags))
                    n += 1
        if n: self.save()
        return n

    def delete_tag(self, tag: str) -> int:
        n = 0
        for shelf in self.shelves:
            for b in shelf["books"]:
                tags = b.get("tags", [])
                if tag in tags:
                    b["tags"] = [t for t in tags if t != tag]
                    n += 1
        if n: self.save()
        return n

    def reload(self):
        """ファイルから読み直す（バックアップ復元後などに使用）。"""
        self.shelves = []; self.active_shelf_id = ""; self.history = []
        self._load()

    # ── 本棚間の移動 ────────────────────────────────────────

    def move_book(self, bid: str, target_id: str) -> bool:
        """本を target_id の本棚へ移動する（先頭へ）。履歴棚へは移動不可。"""
        if target_id == HISTORY_ID:
            return False
        target = next((s for s in self.shelves if s["id"] == target_id), None)
        if target is None:
            return False
        for shelf in self.shelves:
            if shelf["id"] == target_id:
                continue
            for i, b in enumerate(shelf["books"]):
                if b["id"] == bid:
                    book = shelf["books"].pop(i)
                    if not any(x["id"] == bid for x in target["books"]):
                        target["books"].insert(0, book)
                    self._rebuild_path_cache(); self.save()
                    return True
        return False

    def move_many(self, bids: set, target_id: str) -> int:
        moved = 0
        for bid in list(bids):
            if self.move_book(bid, target_id):
                moved += 1
        return moved

    def clear_all_covers(self):
        for shelf in self.shelves:
            for b in shelf["books"]: b["cover_cache"] = ""
        self.save()

    def remap_covers(self, new_dir):
        """全書籍のcover_cacheを新しい保存先（同ファイル名）に張り替える。存在しなければ空。"""
        new_dir = Path(new_dir)
        for shelf in self.shelves:
            for b in shelf["books"]:
                cc = b.get("cover_cache", "")
                if cc:
                    np = new_dir / Path(cc).name
                    b["cover_cache"] = str(np) if np.exists() else ""
        self.save()

    def get(self, bid: str) -> dict | None:
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["id"] == bid: return b
        return None

    def import_folders_as_shelves(self, parent) -> tuple:
        """parent 直下の各サブフォルダを本棚として一括生成し、中の漫画を登録する。

        各サブフォルダ内: アーカイブ(zip/cbz/cbr/rar/pdf/epub)と、画像を含む孫フォルダを
        1冊ずつ登録。サブフォルダ自身が直接画像を持つ場合はそれを1冊として登録。
        返り値: (作成した本棚数, 追加した冊数)。重複パスは自動でスキップ。
        """
        parent = Path(parent)
        arch = {".zip", ".cbz", ".epub", ".kepub"}
        if RAR_SUPPORT: arch |= {".cbr", ".rar"}
        if PDF_SUPPORT: arch |= {".pdf"}

        def has_img(p: Path) -> bool:
            try:
                return any(f.is_file() and f.suffix.lower() in SUPPORTED_EXT for f in p.iterdir())
            except Exception:
                return False

        try:
            subs = sorted((e for e in parent.iterdir() if e.is_dir()), key=lambda e: e.name.lower())
        except Exception:
            return (0, 0)
        now = datetime.now().isoformat()
        created = 0; added = 0
        for sub in subs:
            paths = []
            try:
                for e in sub.iterdir():
                    if e.is_file() and e.suffix.lower() in arch:
                        paths.append(e)
                    elif e.is_dir() and has_img(e):
                        paths.append(e)
            except Exception:
                continue
            if not paths and has_img(sub):
                paths = [sub]            # サブフォルダ自体が1冊（画像フォルダ）
            books = []
            for p in sorted(paths, key=lambda x: x.name.lower()):
                rp = str(p.resolve())
                if rp in self._path_cache:
                    continue
                self._path_cache.add(rp)
                books.append({"id": hashlib.md5(rp.encode()).hexdigest(), "title": p.stem,
                              "path": rp, "last_page": 0, "total_pages": 0, "cover_cache": "",
                              "added_at": now, "last_opened": "", "bookmarks": [],
                              "favorite": False, "tags": [], "view": {}})
            if not books:
                continue
            sid = "shelf_" + hashlib.md5(f"{sub.name}{now}{created}".encode()).hexdigest()[:8]
            self.shelves.append({"id": sid, "name": sub.name, "books": books})
            created += 1; added += len(books)
        if created:
            self.save()
        return (created, added)

    def find_duplicates(self) -> dict:
        """同じファイル名（パスは別）の本をグループ化して返す。{ファイル名: [本,...]}。"""
        from collections import defaultdict
        groups = defaultdict(list)
        for b in self._unique_books():
            groups[Path(b["path"]).name.lower()].append(b)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def find_by_path(self, path: str) -> dict | None:
        """同じファイルパスの本が既に登録されていれば返す（クイックオープンの重複判定用）。"""
        rp = str(Path(path).resolve())
        for shelf in self.shelves:
            for b in shelf["books"]:
                if b["path"] == rp: return b
        return None


class PageSource:
    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        self._type = ""; self._names: list[str] = []
        self._page_count = 0
        self._doc = None  # PDF用に開いたドキュメントをキャッシュ
        self._direction = ""  # 綴じ方向 "rtl"/"ltr"（EPUBから判定・不明は""）
        self._scan()

    @property
    def direction(self) -> str:
        """綴じ方向（"rtl"=右綴じ / "ltr"=左綴じ / ""=不明）。EPUBのみ判定可。"""
        return self._direction

    def _get_doc(self):
        if self._doc is None:
            self._doc = fitz.open(self.path)
        return self._doc

    def close(self):
        if self._doc is not None:
            try: self._doc.close()
            except Exception: pass
            self._doc = None

    def __del__(self):
        self.close()

    @staticmethod
    def _local(tag: str) -> str:
        """名前空間つきタグ名からローカル名だけ取り出す（{ns}item -> item）。"""
        return tag.rsplit("}", 1)[-1]

    def _scan_epub(self) -> list[str]:
        """EPUB(=ZIP)を spine の読み順に辿り、各ページの画像エントリ名を順に返す。

        画像ベース(固定レイアウト＝漫画)向け。spine から画像が拾えない場合は
        ZIP内の全画像をファイル名順に並べてフォールバックする（壊さない）。
        """
        with zipfile.ZipFile(self.path) as zf:
            names = zf.namelist()
            nameset = set(names)
            ordered: list[str] = []
            opf_path = self._epub_opf_path(zf, names)
            if opf_path and opf_path in nameset:
                try:
                    ordered = self._epub_spine_images(zf, opf_path, nameset)
                except Exception:
                    ordered = []
            if not ordered:
                ordered = sorted(n for n in names if Path(n).suffix.lower() in SUPPORTED_EXT)
        return ordered

    @staticmethod
    def _epub_opf_path(zf: "zipfile.ZipFile", names: list[str]) -> str | None:
        """META-INF/container.xml から OPF のパスを得る。無ければ最初の .opf。"""
        try:
            root = ET.fromstring(zf.read("META-INF/container.xml"))
            for el in root.iter():
                if PageSource._local(el.tag) == "rootfile":
                    fp = el.get("full-path")
                    if fp:
                        return fp
        except Exception:
            pass
        return next((n for n in names if n.lower().endswith(".opf")), None)

    def _epub_spine_images(self, zf, opf_path: str, nameset: set) -> list[str]:
        root = ET.fromstring(zf.read(opf_path))
        # manifest: id -> (href, media-type)
        manifest: dict[str, tuple[str, str]] = {}
        spine_ids: list[str] = []
        for el in root.iter():
            tag = self._local(el.tag)
            if tag == "item":
                iid = el.get("id")
                if iid:
                    manifest[iid] = (el.get("href") or "", el.get("media-type") or "")
            elif tag == "itemref":
                idref = el.get("idref")
                if idref:
                    spine_ids.append(idref)
            elif tag == "spine":
                d = (el.get("page-progression-direction") or "").lower()
                if d in ("rtl", "ltr"):
                    self._direction = d

        opf_dir = posixpath.dirname(opf_path)

        def resolve(base_dir: str, href: str) -> str:
            href = href.split("#", 1)[0]                 # アンカー除去
            joined = posixpath.join(base_dir, href) if base_dir else href
            return posixpath.normpath(joined)

        ordered: list[str] = []
        for sid in spine_ids:
            if sid not in manifest:
                continue
            href, mtype = manifest[sid]
            if not href:
                continue
            target = resolve(opf_dir, href)
            # spineが直接画像を指す場合
            if mtype.startswith("image/") or Path(target).suffix.lower() in SUPPORTED_EXT:
                if target in nameset:
                    ordered.append(target)
                continue
            # XHTMLページ → 参照している最初の画像を拾う（固定レイアウト＝1ページ1画像）
            if target not in nameset:
                continue
            try:
                html = zf.read(target).decode("utf-8", "ignore")
            except Exception:
                continue
            page_dir = posixpath.dirname(target)
            for src in re.findall(r'(?:src|xlink:href|href)\s*=\s*["\']([^"\']+)["\']', html):
                if Path(src).suffix.lower() in SUPPORTED_EXT:
                    ip = resolve(page_dir, src)
                    if ip in nameset:
                        ordered.append(ip)
                        break
        return ordered

    def _scan(self):
        p = Path(self.path); ext = p.suffix.lower()
        if ext == ".pdf" and PDF_SUPPORT:
            self._page_count = self._get_doc().page_count
            self._type = "pdf"
        elif ext in (".cbz", ".zip"):
            with zipfile.ZipFile(self.path) as zf:
                self._names = sorted(n for n in zf.namelist() if Path(n).suffix.lower() in SUPPORTED_EXT)
            self._type = "zip"
        elif ext in (".epub", ".kepub"):
            # KEPUB(Kobo) は EPUB に koboSpan を足しただけで構造は同じ。
            # （"book.kepub.epub" は suffix が .epub なのでここに来る）
            self._names = self._scan_epub()
            self._type = "epub"
        elif ext in (".cbr", ".rar") and RAR_SUPPORT:
            with rarfile.RarFile(self.path) as rf:
                self._names = sorted(n for n in rf.namelist() if Path(n).suffix.lower() in SUPPORTED_EXT)
            self._type = "rar"
        elif p.is_dir():
            self._names = sorted(f.name for f in p.iterdir() if f.suffix.lower() in SUPPORTED_EXT)
            self._type = "dir"

    def __len__(self) -> int:
        if self._type == "pdf": return self._page_count
        return len(self._names)

    def ext(self, i: int) -> str:
        """ページ i の拡張子（小文字・先頭ドット付き）。PDFや範囲外は ""。"""
        if self._type == "pdf":
            return ".pdf"
        if 0 <= i < len(self._names):
            return Path(self._names[i]).suffix.lower()
        return ""

    def read(self, i: int) -> bytes:
        if self._type == "pdf":
            # PDFページを画像（PNGバイト列）にレンダリング
            page = self._get_doc().load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(PDF_ZOOM, PDF_ZOOM))
            return pix.tobytes("png")
        n = self._names[i]
        if self._type in ("zip", "epub"):
            with zipfile.ZipFile(self.path) as zf: return zf.read(n)
        elif self._type == "rar":
            with rarfile.RarFile(self.path) as rf: return rf.read(n)
        return (Path(self.path) / n).read_bytes()

    def read_first(self) -> bytes: return self.read(0)
