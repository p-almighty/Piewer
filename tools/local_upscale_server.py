"""Piewer 用ローカル超解像サーバ（開発/実機確認用・配布物には含めない）。

Piewer同梱の local_upscale プラグインが話す相手。画像をPOSTで受け取り、高解像度化
して返す。すべて 127.0.0.1（localhost）で完結＝オフライン・無料・画像はPCの外に出ない。

着色サーバ(local_color_server.py)の双子。違いは「着色」→「超解像（拡大）」だけ。

使い方:
    # ① まず配線確認（依存なし・すぐ動く。Lanczos拡大＋アンシャープの簡易版）
    python tools/local_upscale_server.py
    # → http://127.0.0.1:7861/upscale を Piewer の「AI超解像」エンドポイントに設定

    # ② 本物のモデルに差し替え（torch等が必要。下の cugan backend 参照）
    python tools/local_upscale_server.py --backend cugan --repo path/to/Real-CUGAN \
        --weights-dir path/to/weights --scale 2 --denoise 1 --device cuda

リクエスト/レスポンス（connector/local_upscale の既定に合わせている）:
    - multipart/form-data（ファイル）または application/json（base64）で画像を受け取る
    - 高解像度化した PNG を image/png で返す
"""
import argparse
import io
import os
import sys
import json
import base64
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageFilter

# Windowsコンソール(cp932)でも落ちないように出力を保護
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── 超解像バックエンド ──────────────────────────────────────

class DemoBackend:
    """依存なしの簡易拡大（モデルではない）。配線確認用のプレースホルダ。

    実際のAI超解像ではなく、Lanczos拡大＋アンシャープで“くっきり拡大した風”にする。
    Piewerとサーバが正しく繋がっているか（大きい画像が返るか）を確認するためのもの。
    """
    name = "demo"

    def __init__(self, scale: int = 2):
        self.scale = max(1, int(scale))

    def upscale(self, img: "Image.Image") -> "Image.Image":
        w, h = img.size
        out = img.resize((w * self.scale, h * self.scale), Image.LANCZOS)
        # 拡大でぼけた分を軽く立てる（線画向けの軽いシャープ）
        return out.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))


# denoise 値 → Real-CUGAN の重みファイル名サフィックス
_CUGAN_DENOISE_SUFFIX = {
    -1: "conservative",
    0: "no-denoise",
    1: "denoise1x",
    2: "denoise2x",
    3: "denoise3x",
}


def cugan_weight_name(scale: int, denoise: int) -> str:
    """(scale, denoise) に対応する Real-CUGAN の標準重みファイル名。

    3x/4x には denoise1x/denoise2x が存在しない（公式weights_v3）ため denoise3x へ寄せる。
    """
    suffix = _CUGAN_DENOISE_SUFFIX.get(int(denoise), "denoise1x")
    if int(scale) >= 3 and suffix in ("denoise1x", "denoise2x"):
        suffix = "denoise3x"
    return f"up{int(scale)}x-latest-{suffix}.pth"


class CuganBackend:
    """本物のモデル: Real-CUGAN (bilibili) の推論を呼んで高解像度化。

    https://github.com/bilibili/ailab/tree/main/Real-CUGAN を clone し、その中の
    `upcunet_v3.py` の `RealWaifuUpScaler` を使う。漫画/アニメ線画に最適化された
    超解像で、torch + numpy のみ（basicsr等の追加依存は不要＝ai_runtimeのtorchを流用）。

    重い依存（torch 等）はこのバックエンドの中だけで、Piewer本体には一切入らない。
    GPU(CUDA)があれば --device cuda、--half でfp16でさらに速い。

    必要なもの:
      --repo         clone した Real-CUGAN のパス（中の upcunet_v3.py を import）
      --model        重み(.pth)を直接指定。未指定なら --weights-dir から自動選択。
      --weights-dir  重み置き場。(scale,denoise) からファイル名を組み立てて探す。
    """
    name = "cugan"

    def __init__(self, repo: str, model: str, weights_dir: str, scale: int = 2,
                 denoise: int = 1, device: str = "cpu", half: bool = False,
                 tile: int = 0):
        import numpy as np   # noqa: 遅延import
        self.np = np
        self.scale = int(scale)
        self.tile = int(tile)

        repo = os.path.abspath(repo)
        if repo not in sys.path:
            sys.path.insert(0, repo)

        # 重みの解決: --model 優先、無ければ weights-dir から (scale,denoise) で組み立て
        if model:
            weight = os.path.abspath(model)
        else:
            if not weights_dir:
                raise SystemExit("cugan: --model か --weights-dir のどちらかが必要です")
            weight = os.path.join(os.path.abspath(weights_dir),
                                  cugan_weight_name(scale, denoise))
        if not os.path.exists(weight):
            raise SystemExit(f"cugan: 重みが見つかりません: {weight}")

        try:
            from upcunet_v3 import RealWaifuUpScaler   # リポジトリ内のクラス
        except Exception as e:
            raise SystemExit(
                "cugan: リポジトリの upcunet_v3.py を import できません。"
                f"--repo のパスと依存(torch等)を確認してください（{e}）")

        # RealWaifuUpScaler(scale, weight_path, half, device)
        self.model = RealWaifuUpScaler(str(scale), weight, half, device)

    def upscale(self, img: "Image.Image") -> "Image.Image":
        np = self.np
        arr = np.asarray(img.convert("RGB"))   # HWC uint8 RGB
        # RealWaifuUpScaler.__call__(frame, tile_mode, cache_mode, alpha)
        out = self.model(arr, self.tile, 0, 1)
        out = np.ascontiguousarray(out).astype("uint8")
        return Image.fromarray(out, "RGB")


def make_backend(args):
    if args.backend == "cugan":
        if not args.repo:
            raise SystemExit("cugan backend には --repo（clone先のパス）が必要です")
        return CuganBackend(args.repo, args.model, args.weights_dir, args.scale,
                            args.denoise, args.device, args.half, args.tile)
    return DemoBackend(args.scale)


# ── HTTP ────────────────────────────────────────────────────

def _extract_image(body: bytes, ctype: str) -> bytes:
    """multipart または application/json(base64) から画像バイト列を取り出す。"""
    if "application/json" in (ctype or ""):
        d = json.loads(body.decode("utf-8", "ignore"))
        # 最初に見つかった文字列値を画像とみなす（connector/local_upscaleは {field: dataURL}）
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
            msg = (f"Piewer local upscale server — backend: {backend.name}\n"
                   f"POST an image to {self.path or '/upscale'}").encode("utf-8")
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
                out = backend.upscale(img).convert("RGB")
                buf = io.BytesIO(); out.save(buf, "PNG"); data = buf.getvalue()
            except Exception as e:
                err = f"upscale failed: {e}".encode("utf-8")
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
    ap = argparse.ArgumentParser(description="Piewer ローカル超解像サーバ")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--backend", choices=["demo", "cugan"], default="demo")
    ap.add_argument("--repo", default="", help="cugan: clone した Real-CUGAN のパス")
    ap.add_argument("--model", default="", help="cugan: 重み(.pth)を直接指定")
    ap.add_argument("--weights-dir", default="",
                    help="cugan: 重み置き場（--model未指定時に scale/denoise から自動選択）")
    ap.add_argument("--scale", type=int, default=2, help="拡大率 2 / 3 / 4")
    ap.add_argument("--denoise", type=int, default=1,
                    help="cugan: ノイズ除去 -1=conservative/0=なし/1〜3=強さ")
    ap.add_argument("--half", action="store_true", help="cugan: fp16（CUDAで高速・省VRAM）")
    ap.add_argument("--tile", type=int, default=0,
                    help="cugan: タイル分割モード（0=分割なし。VRAM不足時に1以上）")
    ap.add_argument("--device", default="cpu", help="cpu / cuda（GPUがあれば cuda）")
    args = ap.parse_args()

    backend = make_backend(args)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(backend))
    url = f"http://{args.host}:{args.port}/upscale"
    print(f"Piewer upscale server [{backend.name}] -> {url}")
    print("Set this URL in Piewer: AI upscale -> endpoint. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
