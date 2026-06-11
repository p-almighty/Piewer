"""Piewer 用ローカル着色サーバ（開発/実機確認用・配布物には含めない）。

Piewer同梱の connector プラグインが話す相手。画像をPOSTで受け取り、着色して返す。
すべて 127.0.0.1（localhost）で完結＝オフライン・無料・画像はPCの外に出ない。

使い方:
    # ① まず配線確認（依存なし・すぐ動く。着色は“デモ”の簡易トーン）
    python tools/local_color_server.py
    # → http://127.0.0.1:7860/colorize を Piewer の「AI着色」エンドポイントに設定

    # ② 本物のモデルに差し替え（torch等が必要。下の manga2 backend 参照）
    python tools/local_color_server.py --backend manga2 --weights path/to/generator.pth

リクエスト/レスポンス（connector の既定に合わせている）:
    - multipart/form-data（ファイル）または application/json（base64）で画像を受け取る
    - 着色した PNG を image/png で返す
"""
import argparse
import io
import sys
import json
import base64
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps, ImageEnhance

# Windowsコンソール(cp932)でも落ちないように出力を保護
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── 着色バックエンド ────────────────────────────────────────

class DemoBackend:
    """依存なしの簡易着色（モデルではない）。配線確認用のプレースホルダ。

    実際のAIではなく、輝度→トライトーンの“色がついた風”処理。Piewerとサーバが
    正しく繋がっているかを、色付き画像が返ることで一目で確認するためのもの。
    """
    name = "demo"

    def colorize(self, img: "Image.Image") -> "Image.Image":
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        # 暗=藍 / 中=肌色 / 明=クリーム のトライトーン（色が乗ったと分かる配色）
        return ImageOps.colorize(gray, black=(28, 30, 64),
                                 white=(252, 246, 232), mid=(206, 140, 110))


class Manga2Backend:
    """本物のモデル: manga-colorization-v2 (qweasdd) の推論を呼んで着色。

    https://github.com/qweasdd/manga-colorization-v2 を clone し、その中の
    `MangaColorizator` を使う。重い依存（torch 等）はこのバックエンドの中だけで、
    Piewer本体には一切入らない。GPU(CUDA)があれば --device cuda で数倍速い。

    必要なもの（詳細は tools/README.md）:
      --repo       clone したリポジトリのパス（中の colorizator.py を import する）
      --generator  生成器の重み（既定 <repo>/networks/generator.zip）
      --extractor  特徴抽出器の重み（既定 <repo>/networks/extractor.pth）
    """
    name = "manga2"

    def __init__(self, repo: str, generator: str, extractor: str, device: str = "cpu",
                 size: int = 576, denoise: bool = True, denoise_sigma: int = 25,
                 saturation: float = 1.0):
        import os
        import numpy as np   # noqa: 遅延import
        self.np = np
        # サイズは32の倍数である必要があるモデル仕様に合わせて丸める
        self.size = max(32, size - (size % 32))
        self.denoise = denoise
        self.denoise_sigma = denoise_sigma
        self.saturation = saturation   # 出力の彩度を後処理で調整（>1で濃く）

        repo = os.path.abspath(repo)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        # generator は必須。extractor.pth は推論では未使用（引数はダミー）なので存在チェック不要。
        gen = os.path.abspath(generator) if generator else os.path.join(repo, "networks", "generator.zip")
        ext = os.path.abspath(extractor) if extractor else os.path.join(repo, "networks", "extractor.pth")
        if not os.path.exists(gen):
            raise SystemExit(f"manga2: generator の重みが見つかりません: {gen}")
        # denoiser は MangaColorizator 構築時に必ずロードされる（--no-denoise でも構築は必要）。
        denoise_w = os.path.join(repo, "denoising", "models", "net_rgb.pth")
        if not os.path.exists(denoise_w):
            raise SystemExit(f"manga2: denoiser の重みが見つかりません: {denoise_w}\n"
                             "（README の denoiser 重みを denoising/models/ に置いてください）")
        try:
            from colorizator import MangaColorizator   # リポジトリ内のクラス
        except Exception as e:
            raise SystemExit(
                "manga2: リポジトリの colorizator.py を import できません。"
                f"--repo のパスと依存(torch等)を確認してください（{e}）")
        # denoiser の重みは相対パス 'denoising/models/' で読まれるため、構築の間だけ
        # repo ルートへ移動する（colorize 自体はファイルを読まないので構築後は戻してよい）。
        old = os.getcwd()
        os.chdir(repo)
        try:
            self.model = MangaColorizator(device, gen, ext)
        finally:
            os.chdir(old)

    def colorize(self, img: "Image.Image") -> "Image.Image":
        np = self.np
        arr = np.asarray(img.convert("RGB"), dtype="float32") / 255.0
        # MangaColorizator.set_image(image, size, apply_denoise, denoise_sigma)
        self.model.set_image(arr, self.size, self.denoise, self.denoise_sigma)
        out = self.model.colorize()                 # float 0..1 RGB (H,W,3)
        out = (np.clip(out, 0.0, 1.0) * 255).astype("uint8")
        result = Image.fromarray(out, "RGB").resize(img.size, Image.LANCZOS)
        if abs(self.saturation - 1.0) > 0.01:
            result = ImageEnhance.Color(result).enhance(self.saturation)
        return result


def make_backend(args):
    if args.backend == "manga2":
        if not args.repo:
            raise SystemExit("manga2 backend には --repo（clone先のパス）が必要です")
        return Manga2Backend(args.repo, args.generator, args.extractor, args.device,
                             args.size, not args.no_denoise, args.denoise_sigma,
                             args.saturation)
    return DemoBackend()


# ── HTTP ────────────────────────────────────────────────────

def _extract_image(body: bytes, ctype: str) -> bytes:
    """multipart または application/json(base64) から画像バイト列を取り出す。"""
    if "application/json" in (ctype or ""):
        d = json.loads(body.decode("utf-8", "ignore"))
        # 最初に見つかった文字列値を画像とみなす（connectorは {field: dataURL}）
        for v in d.values():
            if isinstance(v, str):
                s = re.sub(r"^data:[^;]+;base64,", "", v)
                return base64.b64decode(s)
        raise ValueError("JSONに画像が見つかりません")
    # multipart/form-data: boundary で分割し、最初のパートのペイロードを取る
    m = re.search(r"boundary=(.+)$", ctype or "")
    if not m:
        return body   # 不明なら丸ごと画像とみなす
    boundary = m.group(1).strip().strip('"').encode()
    for part in body.split(b"--" + boundary):
        idx = part.find(b"\r\n\r\n")
        if idx == -1:
            continue
        payload = part[idx + 4:]
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        if payload and payload not in (b"--", b"--\r\n"):
            return payload
    raise ValueError("multipartから画像を取り出せません")


def make_handler(backend):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("[server]", self.address_string(), fmt % args)

        def do_GET(self):
            msg = (f"Piewer local color server — backend: {backend.name}\n"
                   f"POST an image to {self.path or '/colorize'}").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers(); self.wfile.write(msg)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                png_in = _extract_image(body, self.headers.get("Content-Type", ""))
                img = Image.open(io.BytesIO(png_in)).convert("RGB")
                out = backend.colorize(img).convert("RGB")
                buf = io.BytesIO(); out.save(buf, "PNG"); data = buf.getvalue()
            except Exception as e:
                err = f"colorize failed: {e}".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers(); self.wfile.write(err)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Piewer ローカル着色サーバ")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--backend", choices=["demo", "manga2"], default="demo")
    ap.add_argument("--repo", default="", help="manga2: clone した manga-colorization-v2 のパス")
    ap.add_argument("--generator", default="", help="manga2: 生成器の重み（既定 <repo>/networks/generator.zip）")
    ap.add_argument("--extractor", default="", help="manga2: 特徴抽出器の重み（既定 <repo>/networks/extractor.pth）")
    ap.add_argument("--size", type=int, default=576, help="manga2: 推論解像度（32の倍数）")
    ap.add_argument("--no-denoise", action="store_true", help="manga2: ノイズ除去をスキップ（重み不要・少し粗い）")
    ap.add_argument("--denoise-sigma", type=int, default=25, help="manga2: ノイズ除去の強さ")
    ap.add_argument("--saturation", type=float, default=1.0,
                    help="manga2: 出力の彩度（色の濃さ）。1.0=そのまま / 1.3〜1.6で濃く / 0.8で淡く")
    ap.add_argument("--device", default="cpu", help="cpu / cuda（GPUがあれば cuda）")
    args = ap.parse_args()

    backend = make_backend(args)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(backend))
    url = f"http://{args.host}:{args.port}/colorize"
    print(f"Piewer color server [{backend.name}] -> {url}")
    print("Set this URL in Piewer: AI colorize -> endpoint. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
