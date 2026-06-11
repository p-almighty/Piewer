"""画質補正＋擬似カラー化（疑似色刷り）。PILのみ・純粋関数（ユーザーデータに触れない）。

2系統の処理を1枚の画像に適用する:
  ①画質補正  : 自動レベル補正 / ガンマ / アンシャープ（見やすく整える。色は塗らない）
  ②擬似カラー化（疑似色刷り）: 輝度→色のグラデーションマップ（ImageOps.colorize）。
     画像内容は理解せず「色がついた風」にする軽量処理（AI着色とは別物）。

設定 dict（config.Settings.image_fx）の形:
  {"on":bool, "autolevel":bool, "gamma":float, "sharpen":bool,
   "color":"none|sepia|blue|warm|cool|quad", "strength":int(0-100)}
"""
from PIL import Image, ImageOps, ImageFilter

DEFAULT = {
    "on": False,
    "autolevel": False,
    "gamma": 1.0,
    "sharpen": False,
    "color": "none",
    "strength": 80,
}

# 擬似色刷りプリセット: 役割キー -> (black, white, mid|None)
#   black=暗部の色 / white=明部の色 / mid=中間調の色（4色刷り風で効く）
COLOR_PRESETS = {
    "sepia": ((34, 22, 10), (255, 244, 214), None),          # セピア
    "blue":  ((8, 18, 56), (226, 238, 255), None),           # 青の2色刷り風
    "warm":  ((40, 12, 8), (255, 236, 200), (196, 96, 72)),  # 暖色
    "cool":  ((10, 22, 44), (224, 238, 255), (96, 150, 196)),  # 寒色
    "quad":  ((26, 14, 40), (255, 246, 214), (208, 92, 84)),  # 4色刷り風（暗=紫み/中=朱/明=クリーム）
    "mmeeya": ((22, 30, 70), (248, 238, 208), (210, 134, 70)),  # 色刷り(紺×橙)＝暗=紺/中=橙/明=クリーム
}

# UI表示用（順序つき）。表示名は呼び出し側で t() に通す。
COLOR_ORDER = (("none", "なし"), ("sepia", "セピア"), ("blue", "青(2色刷り)"),
               ("warm", "暖色"), ("cool", "寒色"), ("quad", "4色刷り風"),
               ("mmeeya", "色刷り(紺×橙)"))


def merge(cfg) -> dict:
    c = dict(DEFAULT)
    if cfg:
        for k in DEFAULT:
            if k in cfg:
                c[k] = cfg[k]
    return c


def active(cfg) -> bool:
    """この設定が実際に画像を変えるなら True（ON かつ何か効果がある）。"""
    c = merge(cfg)
    if not c["on"]:
        return False
    return bool(c["autolevel"] or abs(float(c["gamma"]) - 1.0) > 0.01 or c["sharpen"]
                or (c["color"] in COLOR_PRESETS and int(c["strength"]) > 0))


def signature(cfg):
    """キャッシュキー用の軽量シグネチャ（効果が同じなら同じ値）。"""
    c = merge(cfg)
    if not active(c):
        return ()
    return (bool(c["autolevel"]), round(float(c["gamma"]), 2), bool(c["sharpen"]),
            c["color"], int(c["strength"]))


def _gamma_lut(gamma: float) -> list:
    inv = 1.0 / max(0.05, float(gamma))
    return [min(255, int((i / 255.0) ** inv * 255 + 0.5)) for i in range(256)]


def apply_fx(img: "Image.Image", cfg) -> "Image.Image":
    """設定に従って画像を補正・擬似カラー化して返す（ONでなければそのまま返す）。"""
    c = merge(cfg)
    if not c["on"]:
        return img
    if img.mode != "RGB":
        img = img.convert("RGB")

    # ①画質補正
    if c["autolevel"]:
        try:
            img = ImageOps.autocontrast(img, cutoff=1)
        except Exception:
            pass
    if abs(float(c["gamma"]) - 1.0) > 0.01:
        try:
            img = img.point(_gamma_lut(c["gamma"]) * 3)   # RGB各バンドへ同じLUT
        except Exception:
            pass
    if c["sharpen"]:
        try:
            img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=130, threshold=3))
        except Exception:
            pass

    # ②擬似カラー化（疑似色刷り）
    preset = COLOR_PRESETS.get(c["color"])
    strength = max(0, min(100, int(c["strength"])))
    if preset and strength > 0:
        black, white, mid = preset
        try:
            gray = ImageOps.grayscale(img)   # L
            col = (ImageOps.colorize(gray, black=black, white=white, mid=mid) if mid
                   else ImageOps.colorize(gray, black=black, white=white))
            a = strength / 100.0
            img = col if a >= 1.0 else Image.blend(img, col, a)
        except Exception:
            pass
    return img
