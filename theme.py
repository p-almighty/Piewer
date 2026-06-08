# theme.py — Piewer の配色・角丸を一元管理するテーマ定義。
#
# 「AIっぽい」無機質な青＋カクカクUIをやめ、バイオレット系アクセント＋
# しっかり丸いポップなデザインに統一する。色や丸みを変えたいときはここだけ
# 触れば全体に反映される（インラインQSSも極力この値に合わせている）。

# ── アクセント（バイオレット＝既定） ─────────────────────────
ACCENT        = "#a06cff"   # メインアクセント
ACCENT_HOVER  = "#b488ff"   # ホバー
ACCENT_DEEP   = "#8a4fff"   # 押下・強調
ACCENT_SEL_BG = "#2e2347"   # 選択中カードの背景
ACCENT_SOFT   = "#c9b6ff"   # 見出し等の淡いアクセント文字

# 既定（ソース中のインラインQSSに直書きされている）アクセント色。
# 別のアクセントを選んだとき、setStyleSheet をフックしてこれらを置換する。
_DEFAULT_ACCENT = "#a06cff"
_DEFAULT_HOVER  = "#b488ff"

# アクセントのプリセット（名前 → (アクセント, ホバー)）
ACCENT_PRESETS = {
    "violet": ("#a06cff", "#b488ff"),
    "blue":   ("#5a86ff", "#7ba0ff"),
    "pink":   ("#ff5e9a", "#ff86b3"),
    "green":  ("#3fbf6f", "#5fd98a"),
    "teal":   ("#23b3ad", "#46cfc8"),
    "orange": ("#ff8c42", "#ffa566"),
    "crimson": ("#e0556b", "#f0788a"),
}
ACCENT_LABELS = {"violet": "バイオレット", "blue": "ブルー", "pink": "ピンク",
                 "green": "グリーン", "teal": "ティール", "orange": "オレンジ",
                 "crimson": "レッド"}
current_accent = "violet"

# ── ライトテーマ ─────────────────────────────────────────────
# ダーク既定の配色（インラインQSSに直書きの色）を、明るい配色へ置換するマップ。
# リーダー本体・サムネ・グリッド等の QPainter 描画面は対象外（暗いまま＝読書向き）。
LIGHT = False
_LIGHT_MAP = {
    # 背景（暗→明・ニュートラルなグレー。青紫みを残さない）
    "#131019": "#ededed", "#18151f": "#f5f5f5", "#15121d": "#f1f1f1",
    "#1f1a29": "#eaeaea", "#262032": "#fafafa", "#241f31": "#ffffff",
    "#2b2539": "#ffffff", "#322b45": "#ededed", "#423a5a": "#e0e0e0",
    "#221d31": "#f0f0f0", "#231d33": "#f0f0f0", "#3a3251": "#e4e4e4",
    "#2f2840": "#ece6f5", "#322a45": "#ece6f5",   # 本棚カードのホバー背景（明い紫タイント）
    "#2e2347": "#e6ddfa",                          # 選択中（淡いアクセント色）
    # 罫線（ニュートラル）
    "#393350": "#d6d6d6", "#463d63": "#c8c8c8",
    # テキスト（明→暗）
    "#e8e4f0": "#1c1c1c", "#b8aed0": "#555555", "#8a7fa6": "#6a6a6a",
    "#d8ccff": "#5a4a90", "#bfa6ff": "#6a52a8", "#c9b6ff": "#6a52a8",
    "#b39dff": "#6a52a8", "#a18fd0": "#6a5a90", "#9a8fc0": "#6a6488",
    "#ddd": "#2a2a2a", "#eee": "#1c1c1c", "#ccc": "#3a3a3a", "#bbb": "#464646",
    "#aaa": "#555555", "#999": "#767676", "#888": "#6e6e6e", "#777": "#7c7c7c",
    "#666": "#868686",
    # 色付き本棚カード（暗→明タイント＋文字は濃く）
    "#3a3320": "#fdf3d0", "#463d22": "#f6edc4", "#8a7320": "#caa83a",
    "#ffe08a": "#8a6a10", "#cdb066": "#9a7a20",
    "#1e3330": "#d8f0ea", "#244038": "#c9e8e0", "#2f6f63": "#4f9a8c",
    "#b8f0e6": "#1f6a5e", "#6fb5a8": "#3f8a7c",
    "#1f2c33": "#d8eaf2", "#243640": "#c8e0ee", "#356073": "#4f8aa6",
    "#bfe6f0": "#1f6a82", "#73b0c0": "#3f8090",
    "#2a2433": "#ece6f6", "#5b4a7a": "#b0a0d0",
}


def set_theme(name: str):
    """"dark" / "light" を適用する。"""
    global LIGHT
    LIGHT = (name == "light")


def is_light() -> bool:
    return LIGHT


def set_accent(name: str):
    """アクセント色のプリセットを適用する（theme関数の値も切り替わる）。"""
    global ACCENT, ACCENT_HOVER, ACCENT_DEEP, current_accent
    if name not in ACCENT_PRESETS:
        name = "violet"
    current_accent = name
    ACCENT, ACCENT_HOVER = ACCENT_PRESETS[name]
    ACCENT_DEEP = ACCENT


def themed(qss: str) -> str:
    """インラインQSSの既定アクセント色・ダーク配色を、選択中テーマへ置換する。"""
    if not qss:
        return qss
    if current_accent != "violet":
        qss = qss.replace(_DEFAULT_ACCENT, ACCENT).replace(_DEFAULT_HOVER, ACCENT_HOVER)
    if LIGHT:
        for k, v in _LIGHT_MAP.items():
            qss = qss.replace(k, v)
    return qss


def install_theming():
    """QWidget.setStyleSheet をフックして、適用時にアクセント色を差し替える。"""
    from PySide6.QtWidgets import QWidget
    if getattr(QWidget, "_piewer_themed", False):
        return
    _orig = QWidget.setStyleSheet

    def _patched(self, qss):
        _orig(self, themed(qss))
    QWidget.setStyleSheet = _patched
    QWidget.setStyleSheetRaw = _orig   # 色見本など置換したくない箇所用
    QWidget._piewer_themed = True

# ── 背景（ほんのり紫みのあるダーク） ─────────────────────────
BG_DEEP   = "#131019"   # 最も暗い面（リーダー背景）
BG_APP    = "#18151f"   # アプリ全体・本棚グリッド・カード地
BG_PANEL  = "#1f1a29"   # ツールバー / ヘッダ / ステータスバー
BG_CARD   = "#241f31"   # 本棚カード・追加カード
BG_DIALOG = "#262032"   # ダイアログ・メニュー
BG_INPUT  = "#2b2539"   # 入力欄・チップ・フラットボタン地
BG_FLAT   = "#322b45"   # フラット（枠つき）ボタン
BG_HOVER  = "#423a5a"   # フラットボタンのホバー

# ── 罫線・文字 ───────────────────────────────────────────────
BORDER      = "#393350"
BORDER_SOFT = "#463d63"
TEXT        = "#e8e4f0"
TEXT_SUB    = "#b8aed0"
TEXT_MUTE   = "#8a7fa6"
HEAD        = "#d8ccff"   # 見出し文字

# ── ゴールド（お気に入り・しおり）はそのまま個性として残す ───
GOLD     = "#ffc107"
GOLD_HI  = "#ffd954"

# ── 角丸 ─────────────────────────────────────────────────────
R_CARD   = 14   # 本カード・本棚カード
R_DIALOG = 14
R_INPUT  = 10
R_CHIP   = 14


def pill(h: int) -> int:
    """高さ h のボタンをピル型にする角丸半径。"""
    return max(8, h // 2)


def btn_qss(h: int, font_size: int = 12) -> str:
    """フラット（地味）ボタンのQSS。ピル型・バイオレットホバー。"""
    r = pill(h)
    return (f"QLabel{{background:{BG_INPUT};color:{TEXT_SUB};border-radius:{r}px;"
            f"padding:0 14px;font-size:{font_size}px;}}"
            f" QLabel:hover{{background:{BG_HOVER};color:{TEXT};}}")


def btn_accent_qss(h: int, font_size: int = 12) -> str:
    """アクセント（バイオレット）ボタンのQSS。ピル型。"""
    r = pill(h)
    return (f"QLabel{{background:{ACCENT};color:white;border-radius:{r}px;"
            f"padding:0 14px;font-size:{font_size}px;font-weight:bold;}}"
            f" QLabel:hover{{background:{ACCENT_HOVER};}}")


def btn_disabled_qss(h: int, font_size: int = 12) -> str:
    """無効状態のフラットボタンのQSS。押せないと分かる沈んだグレー（ホバー無し）。"""
    r = pill(h)
    return (f"QLabel{{background:{BG_APP};color:{TEXT_MUTE};border-radius:{r}px;"
            f"padding:0 14px;font-size:{font_size}px;}}")


def toggle_on_qss(h: int, font_size: int = 12) -> str:
    r = pill(h)
    return (f"QLabel{{background:{ACCENT};color:white;border-radius:{r}px;"
            f"padding:0 12px;font-size:{font_size}px;font-weight:bold;}}")


def toggle_off_qss(h: int, font_size: int = 12) -> str:
    r = pill(h)
    return (f"QLabel{{background:{BG_INPUT};color:{TEXT_MUTE};border-radius:{r}px;"
            f"padding:0 12px;font-size:{font_size}px;}}"
            f" QLabel:hover{{background:{BG_HOVER};color:{TEXT};}}")
