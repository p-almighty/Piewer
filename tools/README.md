# tools/ — 開発・実機確認用（配布物には含めない）

## local_color_server.py — ローカル着色サーバ

Piewer同梱の `connector` プラグインが話す相手。`127.0.0.1`（localhost）で完結＝
**オフライン・無料・画像はPCの外に出ない**。

### ① まず配線確認（依存なし・すぐ動く）

```
python tools/local_color_server.py
```

- 既定で `http://127.0.0.1:7860/colorize` を待ち受け（`--port` で変更可）
- 着色は **デモ**（輝度→トライトーンの“色がついた風”。AIではない）。Piewerと
  サーバが正しく繋がっているかを、色付き画像が返ることで確認するためのもの。

Piewer側の設定（HUD「🤖 AI着色」）:
- 有効化 ON / プラグイン `HTTP着色コネクタ`
- エンドポイントURL: `http://127.0.0.1:7860/colorize`
- 送信形式: `multipart`（既定）/ APIキー不要
- 「接続テスト」→ ✓ が出れば疎通OK。本を開くと自動で着色される。

### ② 本物のモデル: manga-colorization-v2（NVIDIA GPU）

漫画専用のGAN着色モデル <https://github.com/qweasdd/manga-colorization-v2> を使います。
重い依存（torch等）は**このサーバの中だけ**。Piewer本体には一切入りません。

#### 1. リポジトリを取得

```
git clone https://github.com/qweasdd/manga-colorization-v2
```

#### 2. 重み（モデルファイル）をDLして配置

リポジトリのREADMEにあるリンク（Google Drive）から入手して、次のように置く:

- `generator.zip`（生成器） → `networks/generator.zip`
- `net_rgb.pth`（denoiser）  → `denoising/models/net_rgb.pth`

> **`extractor.pth` は不要**。推論コード（`Colorizer`）は generator しか読まず、
> `extractor_path` 引数はダミーです（コードを確認済み）。
> denoiser は `MangaColorizator` 構築時に必ず読まれるため、`--no-denoise` を使う場合でも
> `net_rgb.pth` は配置が必要です（着色時のノイズ除去だけがスキップされます）。

#### 3. 依存をインストール（CUDA版torch）

GPUを使うのでCUDA版のtorchを入れます（RTX 3080／新しめのドライバなら cu124 でOK）:

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install opencv-python scikit-image
```

> 確認: `python -c "import torch; print(torch.cuda.is_available())"` が `True` ならGPU認識。
> matplotlib は公式 `inference.py` 専用で、このサーバ経路では不要です。

#### 4. サーバを起動（GPU）

```
python tools/local_color_server.py --backend manga2 ^
    --repo path\to\manga-colorization-v2 --device cuda
```

（generator を既定位置 `<repo>/networks/generator.zip` 以外に置いた場合は `--generator` で指定。
　ノイズ除去をスキップするなら `--no-denoise`。解像度は `--size 576` 等で調整。）

Piewer側の設定はデモのときと同じ（エンドポイント `http://127.0.0.1:7860/colorize`、
multipart）。これで本物のAI着色になります。

#### メモ

- 1ページの着色は GPU で数秒〜。結果はPiewer側でディスクキャッシュされるので、同じ
  ページの2回目以降は即時です。
- AI着色は**学習からの推測**です。実際の色の再現ではなく、ページ間で色がぶれることが
  あります（同じ作品をまとめて読むと髪/服の色が揺れることがある）。
- モデルの重みは各自で入手してください（多くは**非商用ライセンス**）。学習済みモデルを
  動かすだけで、Piewerもこのサーバも“学習”はしません。

> `Manga2Backend` は `MangaColorizator(device, generator, extractor)` →
> `set_image(arr, size, denoise, sigma)` → `colorize()` という上記リポジトリのAPIに
> 合わせています。リポジトリ側の仕様が変わっていたら、ここを調整します。
