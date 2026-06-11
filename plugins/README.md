# Piewer プラグイン

Piewer は「画像を渡す → 加工した画像が返る」という細い契約だけを知り、重い処理
（AI着色など）はプラグイン側に隔離します。本体サイズも依存も増えません。規約に沿って
プラグインを置けば、サードパーティ製でもそのまま読み込まれて動きます。

## 置き場所

次の場所が探索されます（上が優先。同じ `id` なら上が勝つ）:

1. `~/.manga_viewer/plugins/`  — ユーザーが後から入れる場所
2. アプリ同梱の `plugins/`     — 配布物に含まれるリファレンス等

各プラグインは **フォルダ＋`plugin.py`**（推奨。helper等を同梱できる）か、単一の
`.py` ファイルです。`_` や `.` で始まる名前は無視されます。

## 着色プラグインの作り方

`plugin.py` に `register()` を用意し、着色プロバイダを返します。プロバイダは以下を持つ
オブジェクト（ダックタイピング）です。

```python
class MyColorizer:
    id = "my_colorizer"          # 一意なID（英数）
    name = "わたしの着色"         # 表示名
    version = "1.0"              # 版（上げるとキャッシュが自動で分かれる）
    description = "説明文"        # 任意

    def colorize(self, img, opts):       # 必須。PIL.Image(RGB) -> PIL.Image
        # opts は config_fields() で宣言した設定値の dict
        return img                       # 着色した画像を返す

    def available(self):                 # 任意。(使えるか, 理由)
        return (True, "")

    def config_fields(self):             # 任意。設定UIが動的に描画する
        return [
            {"key": "endpoint", "label": "URL", "type": "text", "default": ""},
            {"key": "strength", "label": "強さ", "type": "int", "default": 80},
        ]

def register():
    return MyColorizer()
```

### 設定項目（config_fields）の型

| type | UI | 値 |
|------|----|----|
| `text` | 1行入力 | str |
| `password` | 伏字入力 | str |
| `int` | 数値スピン | int |
| `bool` | チェックボックス | bool |
| `choice` | ドロップダウン（`choices` 必須） | 選んだ値 |

各項目に `help`（補足文）も付けられます。

### 注意

- `colorize` は**ワーカースレッド**から呼ばれます（UIは止まりません）。重くてOK。
- 着色結果は Piewer 側でディスクキャッシュされます（`~/.manga_viewer/ai_color/`）。
  同じページ・同じ設定なら2回目以降はプラグインを呼びません。
- 例外を投げるとそのページは原画のまま表示され、HUDに失敗バッジが出ます。
- 純Python＋PILだけで書けば、固めた exe でもそのまま動きます。torch等の重い依存が
  必要なモデルは「別プロセス（ローカルサーバ）として起動し、HTTPで繋ぐ」構成にすると、
  本体を太らせずに使えます（同梱の `connector` プラグインがその受け口になります）。

## 同梱リファレンス: `connector`（HTTP着色コネクタ）

純Python（標準ライブラリ）＋PILだけで動く汎用コネクタです。画像をHTTPで着色サーバへ
送り、結果を受け取ります。送信先URLを変えるだけで用途を切り替えられます。

- `http://127.0.0.1:xxxx/...` … **ローカル（オフライン・無料）**。画像はPCの外に出ません。
- `https://api.xxx/...`       … クラウドAPI（従量課金・要ネット）。

### 設定（AI着色ダイアログから）

| 項目 | 説明 |
|------|------|
| エンドポイントURL | 着色サーバのURL |
| APIキー（任意） | クラウドで必要なら。ローカルは通常不要 |
| 送信形式 | `multipart`（ファイル送信）/ `base64-json`（JSONにbase64で載せる） |
| 画像フィールド名 | 送信時のフィールド/キー名（既定 `image`） |
| 応答内の画像キー | JSON応答のときの画像の場所（`.`区切り。空なら自動探索） |
| 送信前の最大辺(px) | 大きい画像を縮小してから送る（速度/費用対策） |
| タイムアウト(秒) | 1ページを待つ最大秒数 |

サーバの応答は「画像そのもの（`Content-Type: image/*`）」でも「JSON（中にbase64画像
またはURL）」でも構いません。JSONのときは `output` / `image` / `b64_json` / `url` 等を
自動で探します。見つからなければ「応答内の画像キー」で場所を指定してください。
