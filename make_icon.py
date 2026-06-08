"""Piewer アプリアイコン生成スクリプト。
漫画を模したポップなデザインの .ico / .png を生成する。
"""
import math
from PIL import Image, ImageDraw, ImageFont

S = 512  # 生成解像度


def rounded_rect(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ── 背景：角丸の縦グラデーション（ポップなピンク→パープル）
    top = (0x55, 0x88, 0xff)     # アプリのアクセントブルー
    bot = (0xff, 0x5e, 0x9a)     # ポップなピンク
    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bgd = ImageDraw.Draw(bg)
    for y in range(S):
        bgd.line([(0, y), (S, y)], fill=lerp(top, bot, y / S) + (255,))
    # 角丸マスク
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=110, fill=255)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # ── 集中線（マンガの効果線）背景に放射状にうっすら
    cx, cy = int(S * 0.62), int(S * 0.42)
    for i in range(36):
        ang = i * (math.pi * 2 / 36)
        x2 = cx + math.cos(ang) * S
        y2 = cy + math.sin(ang) * S
        d.line([(cx, cy), (x2, y2)], fill=(255, 255, 255, 22), width=6)

    # ── 開いた本（見開き漫画）を中央に
    # 影
    d.polygon([(96, 360), (256, 326), (416, 360), (416, 392), (256, 358), (96, 392)],
              fill=(0, 0, 0, 60))
    # 左ページ
    d.polygon([(100, 150), (256, 120), (256, 350), (100, 380)],
              fill=(255, 255, 255, 255))
    # 右ページ
    d.polygon([(412, 150), (256, 120), (256, 350), (412, 380)],
              fill=(245, 247, 255, 255))
    # 背表紙の線
    d.line([(256, 120), (256, 350)], fill=(120, 130, 160), width=5)
    # ページの罫線（コマ割り風）
    for yy, x0frac in [(190, 0.0), (235, 0.0), (280, 0.0)]:
        d.line([(120, yy), (244, yy - 14)], fill=(200, 205, 220), width=4)
        d.line([(268, yy - 14), (392, yy)], fill=(200, 205, 220), width=4)

    # ── 吹き出し（スピーチバブル）右上にポップに
    bx0, by0, bx1, by1 = 286, 78, 452, 196
    d.ellipse([bx0, by0, bx1, by1], fill=(255, 214, 64, 255),
              outline=(40, 40, 60), width=8)
    # しっぽ
    d.polygon([(330, 178), (360, 176), (322, 232)], fill=(255, 214, 64, 255),
              outline=(40, 40, 60))
    d.polygon([(334, 182), (356, 180), (326, 224)], fill=(255, 214, 64, 255))

    # 吹き出しの中に「!?」をビビッドに
    try:
        font = ImageFont.truetype("arialbd.ttf", 96)
    except Exception:
        font = ImageFont.load_default()
    txt = "!?"
    tb = d.textbbox((0, 0), txt, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((bx0 + bx1) / 2 - tw / 2 - tb[0], (by0 + by1) / 2 - th / 2 - tb[1]),
           txt, font=font, fill=(0xe0, 0x33, 0x55))

    # ── 星のきらめき（ポップ要素）
    def star(cx, cy, r, color):
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rad = r if k % 2 == 0 else r * 0.45
            pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
        d.polygon(pts, fill=color)
    star(140, 110, 34, (255, 255, 255, 235))
    star(120, 420, 22, (255, 255, 255, 220))
    star(430, 300, 18, (255, 255, 255, 210))

    # 保存
    img.save("piewer.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save("piewer.ico", sizes=sizes)
    print("created piewer.png / piewer.ico")


if __name__ == "__main__":
    make()
