"""リファレンス着色プラグイン: HTTPコネクタ。

純Python（標準ライブラリの urllib）＋ PIL だけで動く＝本体に重い依存を増やさない。
画像をHTTPで着色サーバへ送り、着色済み画像を受け取って返す。送信先URLを
  ・http://127.0.0.1:xxxx/...  にすればローカル（オフライン・無料・画像は自PC内）
  ・https://api.xxx/...        にすればクラウドAPI
…と、同じ仕組みでどちらにも繋げられる。

レスポンスは「画像そのもの(Content-Type: image/*)」か「JSON(中にbase64画像 or 画像URL)」の
両方に対応。JSONのときは response_key（"."区切りのパス）で画像の場所を指定する。
"""
import io
import os
import re
import json
import base64
import uuid
import urllib.request
import urllib.error

from PIL import Image


class HttpColorizer:
    id = "connector"
    name = "HTTP着色コネクタ"
    version = "1.0"
    description = ("画像をHTTPで着色サーバへ送り、結果を受け取ります。"
                   "URLを localhost にすればオフライン・無料、クラウドAPIにも繋げます。")

    def config_fields(self):
        return [
            {"key": "endpoint", "label": "エンドポイントURL", "type": "text", "default": "",
             "help": "例) http://127.0.0.1:7860/colorize （ローカル） / https://api.example.com/v1/colorize"},
            {"key": "api_key", "label": "APIキー（任意）", "type": "password", "default": "",
             "help": "クラウドAPIで必要なら入力。ローカルサーバでは通常不要。"},
            {"key": "auth_header", "label": "認証ヘッダ名", "type": "text", "default": "Authorization",
             "help": "APIキーを載せるヘッダ名。"},
            {"key": "auth_prefix", "label": "認証値の接頭辞", "type": "text", "default": "Bearer ",
             "help": '例) "Bearer "（末尾の空白も含む）。不要なら空に。'},
            {"key": "mode", "label": "送信形式", "type": "choice",
             "choices": ["multipart", "base64-json"], "default": "multipart",
             "help": "multipart=ファイルとして送信 / base64-json=JSONにbase64で載せて送信。"},
            {"key": "field", "label": "画像フィールド名", "type": "text", "default": "image",
             "help": "multipartのファイル名 / base64-jsonのキー名。"},
            {"key": "response_key", "label": "応答内の画像キー", "type": "text", "default": "",
             "help": ('JSON応答のとき、画像base64またはURLの場所。"."区切り。'
                      '空なら image/output/data/b64_json/url を自動探索。応答が画像そのものなら無視。')},
            {"key": "max_side", "label": "送信前の最大辺(px)", "type": "int", "default": 1600,
             "help": "大きすぎる画像は縮小してから送る（速度/費用対策）。0で無効。"},
            {"key": "timeout", "label": "タイムアウト(秒)", "type": "int", "default": 120,
             "help": "1ページの着色を待つ最大秒数。"},
        ]

    def available(self):
        # 設定はページごとに opts で渡るため、ここでは常に「使える」。
        # 実際の接続失敗は colorize 時に例外として表面化する。
        return (True, "")

    # ── 本体 ───────────────────────────────────────────────

    def colorize(self, img: "Image.Image", opts: dict) -> "Image.Image":
        endpoint = str((opts or {}).get("endpoint", "")).strip()
        if not endpoint:
            raise ValueError("エンドポイントURLが未設定です（AI着色の設定から入力してください）")
        max_side = int((opts or {}).get("max_side", 1600) or 0)
        timeout = int((opts or {}).get("timeout", 120) or 120)
        field = str((opts or {}).get("field", "image") or "image")
        mode = str((opts or {}).get("mode", "multipart") or "multipart")

        send = img.convert("RGB")
        if max_side > 0 and max(send.size) > max_side:
            r = max_side / max(send.size)
            send = send.resize((max(1, int(send.width * r)), max(1, int(send.height * r))),
                               Image.LANCZOS)
        buf = io.BytesIO(); send.save(buf, "PNG"); png = buf.getvalue()

        headers = {}
        key = str((opts or {}).get("api_key", "")).strip()
        if key:
            hname = str((opts or {}).get("auth_header", "Authorization") or "Authorization")
            prefix = str((opts or {}).get("auth_prefix", "Bearer "))
            headers[hname] = prefix + key

        if mode == "base64-json":
            body, ctype = self._build_json(field, png)
        else:
            body, ctype = self._build_multipart(field, png)
        headers["Content-Type"] = ctype

        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                resp_ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            raise RuntimeError(f"着色サーバがエラーを返しました (HTTP {e.code}) {detail}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"着色サーバに接続できません: {e.reason}") from None

        out_bytes = self._extract_image(raw, resp_ctype, opts or {}, timeout)
        return Image.open(io.BytesIO(out_bytes)).convert("RGB")

    # ── リクエスト組み立て ──────────────────────────────────

    @staticmethod
    def _build_multipart(field: str, png: bytes):
        boundary = "----PiewerBoundary" + uuid.uuid4().hex
        pre = (f"--{boundary}\r\n"
               f'Content-Disposition: form-data; name="{field}"; filename="page.png"\r\n'
               f"Content-Type: image/png\r\n\r\n").encode("utf-8")
        post = f"\r\n--{boundary}--\r\n".encode("utf-8")
        return pre + png + post, f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _build_json(field: str, png: bytes):
        b64 = base64.b64encode(png).decode("ascii")
        payload = {field: "data:image/png;base64," + b64}
        return json.dumps(payload).encode("utf-8"), "application/json"

    # ── レスポンス解釈 ──────────────────────────────────────

    def _extract_image(self, raw: bytes, ctype: str, opts: dict, timeout: int) -> bytes:
        # 画像そのものが返ってきた場合
        if "image/" in (ctype or "") or not self._looks_json(raw):
            return raw
        try:
            data = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            return raw   # JSONに見えてパースできない＝画像バイト列とみなす
        val = self._pick(data, str(opts.get("response_key", "")).strip())
        if val is None:
            raise RuntimeError("応答JSONから画像が見つかりませんでした（応答内の画像キーを設定してください）")
        if isinstance(val, str):
            if val.startswith(("http://", "https://")):
                return self._fetch_url(val, opts, timeout)
            return self._b64_to_bytes(val)
        raise RuntimeError("応答JSONの画像フィールドが文字列ではありません")

    @staticmethod
    def _looks_json(raw: bytes) -> bool:
        head = raw[:64].lstrip()
        return head[:1] in (b"{", b"[")

    @staticmethod
    def _b64_to_bytes(s: str) -> bytes:
        s = re.sub(r"^data:[^;]+;base64,", "", s.strip())
        return base64.b64decode(s)

    def _fetch_url(self, url: str, opts: dict, timeout: int) -> bytes:
        headers = {}
        key = str(opts.get("api_key", "")).strip()
        if key:
            hname = str(opts.get("auth_header", "Authorization") or "Authorization")
            headers[hname] = str(opts.get("auth_prefix", "Bearer ")) + key
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _pick(self, data, key_path: str):
        """JSONから画像値を取り出す。key_path 指定があれば優先、無ければ自動探索。"""
        if key_path:
            cur = data
            for part in key_path.split("."):
                if isinstance(cur, list):
                    try:
                        cur = cur[int(part)]
                    except (ValueError, IndexError):
                        return None
                elif isinstance(cur, dict):
                    cur = cur.get(part)
                else:
                    return None
                if cur is None:
                    return None
            return cur
        # 自動探索: よくあるキーを順に
        for k in ("image", "output", "result", "data", "b64_json", "url", "image_url"):
            v = self._dig(data, k)
            if isinstance(v, str) and v:
                return v
        return None

    def _dig(self, data, key):
        """ネストしたdict/listを浅く辿って key の最初の文字列値を探す。"""
        if isinstance(data, dict):
            if isinstance(data.get(key), str):
                return data[key]
            for v in data.values():
                r = self._dig(v, key)
                if r is not None:
                    return r
        elif isinstance(data, list):
            for v in data:
                r = self._dig(v, key)
                if r is not None:
                    return r
        return None


def register():
    return HttpColorizer()
