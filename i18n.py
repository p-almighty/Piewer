# i18n.py — 軽量な日英バイリンガル対応
#
# 日本語の原文をキーに英訳を引く方式。
#   - lang == "ja": 原文をそのまま返す（日本語の挙動は一切変えない）
#   - lang == "en": 辞書にあれば英訳、無ければ原文（日本語）にフォールバック
# プレースホルダ付きの文言は t("...{n}...").format(n=...) のように使う。

_lang = "ja"


def set_lang(lang: str):
    global _lang
    _lang = "en" if str(lang).lower().startswith("en") else "ja"


def get_lang() -> str:
    return _lang


def t(s: str) -> str:
    if _lang == "ja":
        return s
    return _EN.get(s, s)


_EN = {
    # ── 仮想本棚名 / ショートカット名（config.py の定数）──
    "最近読んだ本": "Recently Read",
    "お気に入り": "Favorites",
    "本棚1": "Bookshelf 1",
    "次のページ": "Next page",
    "前のページ": "Previous page",
    "最初のページ": "First page",
    "最後のページ": "Last page",
    "全画面の切り替え": "Toggle fullscreen",
    "本棚に戻る": "Back to shelves",
    "しおりの追加・解除": "Add / remove bookmark",
    "次のしおりへジャンプ": "Jump to next bookmark",
    "前のしおりへジャンプ": "Jump to previous bookmark",
    "メニュー(HUD)の表示切替": "Toggle menu (HUD)",
    "バックアップ形式ではありません": "Not a backup file",

    # ── manga_viewer.py ──
    "「{name}」 — {n} 冊": "“{name}” — {n} books",
    "エラー": "Error",
    "ファイルが見つかりません:\n{path}": "File not found:\n{path}",
    "読み込める画像がありません。": "No readable images.",
    "読み込み失敗:\n{e}": "Failed to open:\n{e}",
    "どこから読みますか？": "Where would you like to start?",
    "最初から読む": "From the beginning",
    "続きから読む": "Continue",
    "キャンセル": "Cancel",

    # ── shelf_view.py ──
    "本棚を選択してください": "Select a shelf",
    "（本棚はドラッグで並び替えできます）": "(Drag shelves to reorder)",
    "{n} 冊": "{n} books",
    "新しい本棚": "New shelf",
    "名前変更": "Rename",
    "削除": "Delete",
    "本棚の名前:": "Shelf name:",
    "名前を変更": "Rename",
    "新しい名前:": "New name:",
    "「{name}」を削除しますか？\n（{n} 冊の情報も削除されます）":
        "Delete “{name}”?\n(Info for {n} book(s) will also be removed.)",

    # ── library_view.py: ツールバー ──
    "⌂ 本棚一覧": "⌂ Shelves",
    "+ ファイル": "+ File",
    "⚙ 設定": "⚙ Settings",
    "並び替え ▾": "Sort ▾",
    "サイズ:": "Size:",
    "小": "S", "中": "M", "大": "L",
    "🔍 検索...": "🔍 Search...",
    "全棚": "All",
    "全ての本棚を横断して検索": "Search across all shelves",
    "🏷 ファイル名から自動タグ付け（実験的）": "🏷 Auto-tag from filenames (experimental)",
    "ファイル名から自動タグ付け（実験的）": "Auto-tag from filenames (experimental)",
    "ファイル名から作者・サークル・原作・イベント等を抽出してタグを付けます。\n既存のタグは消さず追加するだけです。":
        "Extract artist / circle / parody / event etc. from filenames and add them as tags.\nExisting tags are kept; tags are only added.",
    "※ 実験的機能です。ファイル名の付け方によっては誤って抽出することがあります。":
        "* Experimental: depending on how files are named, tags may be extracted incorrectly.",
    "原作": "Parody",
    "イベント・その他": "Event / Other",
    "親フォルダ名": "Parent folder",
    "🎨  外観": "🎨  Appearance",
    "テーマ:": "Theme:", "ダーク": "Dark", "ライト": "Light",
    "テーマ・アクセント色は再起動後に全体へ反映されます。":
        "Theme and accent color apply everywhere after a restart.",
    "バイオレット": "Violet", "ブルー": "Blue", "ピンク": "Pink", "グリーン": "Green",
    "ティール": "Teal", "オレンジ": "Orange", "レッド": "Red",
    "📊 読書統計": "📊 Reading stats",
    "📊  読書統計": "📊  Reading stats",
    "蔵書数・進捗・よく読む作者などを表示します。":
        "Show your library size, progress, most-read artists, and more.",
    "🔁 重複を検出": "🔁 Find duplicates", "🔁  重複を検出": "🔁  Find duplicates",
    "同じファイル名の本を見つけて整理します。": "Find books with the same filename and clean them up.",
    "📂  フォルダ構成から本棚を作成": "📂  Build shelves from folder structure",
    "選んだフォルダ直下の各サブフォルダを本棚として一括取り込みします。":
        "Import each subfolder of the chosen folder as a shelf.",
    "本棚にするフォルダ（の親）を選択": "Choose the parent folder",
    "{s} 個の本棚に {b} 冊を取り込みました。": "Imported {b} book(s) into {s} shelves.",
    "取り込める本棚（サブフォルダ）が見つかりませんでした。": "No importable subfolders were found.",
    "重複の可能性: {g} グループ / {b} 冊": "Possible duplicates: {g} groups / {b} books",
    "重複は見つかりませんでした。": "No duplicates found.",
    "※ 各グループで残す1冊以外にチェックが入っています": "* Every copy except the first in each group is checked",
    "チェックした本を削除": "Delete checked",
    "チェックした {n} 冊を本棚から削除しますか？\n（元のファイルは削除されません）":
        "Remove the {n} checked book(s) from your library?\n(The original files are not deleted)",
    "接頭辞をつける（作者: など）": "Add prefixes (e.g. Artist:)",
    "{books} 冊に {tags} 種類のタグを付けます": "{tags} tag(s) will be added across {books} book(s)",
    "付けられるタグが見つかりませんでした。": "No tags could be extracted.",
    "適用": "Apply",
    "{n} 冊にタグを付けました。": "Tagged {n} book(s).",
    "📁 フォルダから開く": "📁 Browse folders",
    "最近追加した本": "Recently Added",
    "続きを読む": "Continue Reading",
    "読みかけの本はありません": "No books in progress",
    "まだ本が追加されていません": "No books added yet",
    "選択した {n} 冊を本棚から削除しますか？\n（元のファイルは削除されません）":
        "Remove the selected {n} book(s) from your library?\n(The original files are not deleted)",
    "🎲 ランダム": "🎲 Random",
    "全本棚からランダムに1冊開く": "Open a random book from all shelves",
    "この本棚からランダムに1冊開く": "Open a random book from this shelf",
    "ランダム": "Random",
    "本が登録されていません。": "No books have been added.",
    "フォルダから開く": "Browse folders",
    "フォルダ／圧縮ファイルをダブルクリックで開きます": "Double-click a folder or archive to open it",
    "📖 このフォルダを開く": "📖 Open this folder",
    "上下ドラッグで拡大縮小": "Drag up/down to zoom",
    "画面を上下にドラッグして無段階に拡大・縮小します（ポインタ位置を中心に拡大）。":
        "Drag the page up or down to zoom smoothly (centered on the pointer).",
    "📖  本を開いたとき": "📖  When opening a book",
    "続きから": "Resume", "毎回確認": "Ask each time", "最初から": "From start",
    "「続きから」は前回の続きを開きます（最初に戻るには「最初」ボタンやHomeキー）。":
        "\"Resume\" opens where you left off (use the \"First\" button or Home key to go back to the start).",
    "お気に入り・最近読んだ本には直接追加できません（通常の本棚に追加してください）":
        "Can't add directly to Favorites / Recently read (add to a normal shelf instead)",
    "🏷 絞り込み": "🏷 Filter",
    "絞り込み": "Filter",
    "🔍 タグを検索...": "🔍 Search tags...",
    "全 {total} タグ / 選択中 {n}": "{total} tags / {n} selected",
    "すべて解除": "Clear all",
    "状態:": "Status:",
    "未読": "Unread", "既読": "Read",
    "タグ一致:": "Tag match:",
    "いずれか": "Any", "すべて": "All",
    "📗 既読にする": "📗 Mark as read", "📕 未読に戻す": "📕 Mark as unread",
    "全て選択": "Select all",
    "検索でヒットしたタグをすべて選択": "Select all tags matching the search",
    "選択中: ": "Selected: ",
    "タグ未選択（タップして絞り込み）": "No tags selected (tap a tag to filter)",
    "クリックで解除": "Click to remove",
    "🏷  タグ": "🏷  Tags",
    "追加時に自動タグ付け（実験的）": "Auto-tag on add (experimental)",
    "本を追加したとき、ファイル名から作者・サークル・原作・イベントを自動でタグ付けします。":
        "When you add books, automatically tag them (artist / circle / parody / event) from the filename.",
    "選択削除モード": "Select & Delete",
    "＋\n\nここをクリックして漫画を追加": "＋\n\nClick here to add manga",
    "全選択": "Select all",
    "全解除": "Deselect all",
    "別の本棚へ移動": "Move to another shelf",
    "選択した本を削除": "Delete selected",
    "{n} 冊選択中": "{n} selected",
    # 並び替えラベル
    "登録順": "Added", "ファイル名": "Filename",
    "最近読んだ順": "Recently read", "進捗順": "Progress",
    "並び替え: {label} ▾": "Sort: {label} ▾",
    # 絞り込みメニュー
    "★ お気に入りのみ": "★ Favorites only",
    "タグ": "Tags",
    "絞り込みを解除": "Clear filter",
    "🏷 絞り込み ({n})": "🏷 Filter ({n})",
    # カード右クリックメニュー
    "★ お気に入りを解除": "★ Remove from favorites",
    "☆ お気に入りに追加": "☆ Add to favorites",
    "🏷 タグを編集…": "🏷 Edit tags…",
    "📁 別の本棚へ移動": "📁 Move to another shelf",
    "（他に本棚がありません）": "(No other shelves)",
    "お気に入りから外す": "Remove from favorites",
    "履歴から削除": "Remove from history",
    "本棚から削除": "Remove from shelf",
    # 移動
    "移動できません": "Can't move",
    "履歴からは移動できません。元の本棚で操作してください。":
        "Can't move from history. Please use the original shelf.",
    "移動先がありません": "No destination",
    "他に本棚がありません。先に本棚を作成してください。":
        "No other shelves. Please create one first.",
    "「{name}」へ移動": "Move to “{name}”",
    # 選択削除
    "選択した {n} 冊を履歴から外しますか？\n（本そのものは削除されません）":
        "Remove the selected {n} book(s) from history?\n(The books themselves are not deleted.)",
    "選択した {n} 冊をお気に入りから外しますか？\n（本そのものは削除されません）":
        "Remove the selected {n} book(s) from favorites?\n(The books themselves are not deleted.)",
    "削除確認": "Confirm deletion",
    "選択した {n} 冊を削除しますか？": "Delete the selected {n} book(s)?",
    # 空棚
    "お気に入りの本がありません\n（本の表紙の右上「★」をクリックで登録）":
        "No favorites yet\n(Click the ★ at the top-right of a cover to add)",
    "まだ読んだ本がありません": "No recently read books yet",
    # ファイル追加 / 重複
    "漫画ファイル ({exts});;すべて (*)": "Manga files ({exts});;All files (*)",
    "ファイルを追加": "Add files",
    "重複ファイル": "Duplicate files",
    "以下の {n} 件のファイルはすでに登録されています:":
        "The following {n} file(s) are already registered:",
    # バックアップ
    "バックアップを保存": "Save backup",
    "Piewer バックアップ (*.json)": "Piewer backup (*.json)",
    "完了": "Done",
    "バックアップを保存しました:\n{path}": "Backup saved:\n{path}",
    "保存に失敗しました:\n{e}": "Failed to save:\n{e}",
    "復元の確認": "Confirm restore",
    "バックアップから復元すると、現在の本棚・設定は置き換わります。続けますか？":
        "Restoring will replace your current shelves and settings. Continue?",
    "バックアップを選択": "Choose a backup",
    "Piewer バックアップ (*.json);;すべて (*)": "Piewer backup (*.json);;All files (*)",
    "復元に失敗しました:\n{e}": "Failed to restore:\n{e}",
    "復元しました。": "Restored.",
    # 設定ダイアログ
    "設定": "Settings",
    "「{name}」の設定": "Settings for “{name}”",
    "✏  本棚の名前を変更": "✏  Rename shelf",
    "この本棚の表示名を変更します。": "Change this shelf's display name.",
    "お気に入り・履歴棚は名前を変更できません。": "Favorites/History shelves can't be renamed.",
    "🖼  サムネイルを再生成": "🖼  Regenerate thumbnails",
    "すべての表紙キャッシュを削除して作り直します。表紙がずれた・更新したいときに。":
        "Delete and rebuild all cover caches. Use when covers are wrong or outdated.",
    "📁  カバー画像の保存先を変更": "📁  Change cover image folder",
    "現在: {dir}": "Current: {dir}",
    "本棚を開いたときのスクロール位置": "Scroll position when opening a shelf",
    "前回の位置": "Last position",
    "一番上から": "From top",
    "「前回の位置」は本棚ごとに前回見ていた位置で開きます。":
        "“Last position” opens each shelf where you last left it.",
    "🏷  タグの管理": "🏷  Manage tags",
    "タグの名前変更・削除をまとめて行います。": "Rename or delete tags in bulk.",
    "💾  バックアップを保存": "💾  Save backup",
    "本棚と設定を1つのファイルに書き出します。": "Export shelves and settings to a single file.",
    "📥  バックアップから復元": "📥  Restore from backup",
    "保存したバックアップを読み込みます（現在のデータは置き換わります）。":
        "Load a saved backup (replaces current data).",
    "言語 / Language": "言語 / Language",
    "日本語": "日本語", "English": "English",
    "言語はすぐに切り替わります。": "The language switches immediately.",
    # 保存先変更
    "カバー画像の保存先を選択": "Choose cover image folder",
    "保存先の変更": "Change folder",
    "カバー画像の保存先を変更します。\n\n新: {new_dir}\n\n":
        "Change the cover image folder.\n\nNew: {new_dir}\n\n",
    "既存のキャッシュ画像を新しい場所へ移動しますか？\n":
        "Move existing cached images to the new location?\n",
    "（「いいえ」を選ぶと次回以降の生成分のみ新しい場所に保存されます）":
        "(Choose No to store only newly generated images there.)",
    "保存先を設定できませんでした:\n{e}": "Couldn't set the folder:\n{e}",
    "{moved} 件のカバー画像を移動しました。\n保存先:\n{applied}":
        "Moved {moved} cover image(s).\nFolder:\n{applied}",
    "保存先を変更しました:\n{applied}": "Changed folder:\n{applied}",

    # ── widgets.py: 各ダイアログ ──
    "ショートカットの設定": "Shortcut Settings",
    "各操作の「変更」を押し、割り当てたいキーを押してください。":
        "Press “Change” for an action, then press the key to assign.",
    "（Esc で取消・1操作1キー）": "(Esc to cancel · one key per action)",
    "変更": "Change",
    "すべて既定に戻す": "Reset all to default",
    "閉じる": "Close",
    "（なし）": "(none)",
    "キーを押してください…": "Press a key…",
    "{name} のヘルプ": "{name} Help",
    "⌨ ショートカット設定": "⌨ Shortcut settings",
    "タグを編集": "Edit Tags",
    "タグをクリックで追加 / 解除。新しいタグは下の欄から追加できます。":
        "Click a tag to add/remove. Add new tags in the field below.",
    "🕘 最近つけたタグ": "🕘 Recent tags",
    "（まだタグがありません。下から追加してください）":
        "(No tags yet. Add one below.)",
    "新しいタグを入力して Enter": "Type a new tag and press Enter",
    "＋ 追加": "＋ Add",
    "保存": "Save",
    "🔍 AI超解像（高解像度化）": "🔍 AI Upscale (super-resolution)",
    "AI超解像を有効にする（表示より小さいページを自動で高精細化）":
        "Enable AI upscale (auto-sharpen pages smaller than the display)",
    "超解像プラグインが見つかりません。plugins/local_upscale を確認してください。":
        "No upscale plugin found. Check plugins/local_upscale.",
    "拡大率": "Scale",
    "接続テスト": "Test connection",
    "テスト中…": "Testing…",
    "結果が空でした。": "The result was empty.",
    "接続成功（ただし拡大されていません。サーバの拡大率を確認）。":
        "Connected, but no upscaling occurred (check the server scale).",
    "接続成功。超解像サーバから拡大画像を受け取れました。":
        "Connected. Received an upscaled image from the server.",
    "接続先はローカル超解像サーバのURLです（例: tools/local_upscale_server.py を起動）。拡大率を変えたら「高解像度データを削除」で作り直してください。":
        "The endpoint is your local upscale server URL (e.g. run tools/local_upscale_server.py). After changing the scale, use \"Delete upscaled data\" to rebuild.",
    "高解像度データを削除": "Delete upscaled data",
    "高解像度データ: {mb:.1f} MB": "Upscaled data: {mb:.1f} MB",
    "高解像度データ: 0.0 MB（削除するものはありません）": "Upscaled data: 0.0 MB (nothing to delete)",
    "高解像度データの削除": "Delete upscaled data",
    "保存済みの高解像度データを全て削除しますか？\n（次に開いたページから作り直されます）":
        "Delete all saved upscaled data?\n(It will be rebuilt from the next page you open.)",
    "🔍 高解像度化中…": "🔍 Upscaling…",
    "🔍 高解像度化に失敗しました（設定/接続を確認）":
        "🔍 Upscale failed (check settings/connection)",
    "🔍 超解像サーバ起動中…（初回はモデル読込で時間がかかります）":
        "🔍 Starting upscale server… (first run loads the model, please wait)",
    "🔍 サーバエラー: ": "🔍 Server error: ",
    "超解像サーバ（Piewerが自動で起動できます）":
        "Upscale server (Piewer can start it for you)",
    "Piewerでサーバを自動起動する": "Let Piewer start the server automatically",
    "実行": "Run on",
    "CPU": "CPU",
    "GPU(CUDA)": "GPU (CUDA)",
    "起動": "Start",
    "停止": "Stop",
    "停止中": "Stopped",
    "起動中…": "Starting…",
    "実行中": "Running",
    "エラー: ": "Error: ",
    "Real-CUGANを準備（コード＋重み）": "Set up Real-CUGAN (code + weights)",
    "Real-CUGAN 準備済み（再取得）": "Real-CUGAN ready (re-download)",
    "Real-CUGAN の準備が完了しました。": "Real-CUGAN is ready.",
    "ダウンロード中…（torchは着色の準備分を使います）":
        "Downloading… (reuses torch from the colorize setup)",
    "低解像度のページをAIで高精細に拡大します。表示より小さいページにだけ自動で効きます。":
        "Upscales low-resolution pages with AI. Applies only to pages smaller than the display.",
    "① 仕上がりと実行先を選ぶ": "① Choose quality and where to run",
    "拡大": "Scale",
    "2倍（速い）": "2x (faster)",
    "4倍（精細）": "4x (sharper)",
    "② ボタンひとつで準備する": "② Set up with one button",
    "▶ 自動でセットアップして有効にする": "▶ Auto setup and enable",
    "有効にする（小さいページを自動で高解像度化）":
        "Enable (auto-upscale small pages)",
    "詳細設定 ▾": "Advanced ▾",
    "詳細設定 ▴": "Advanced ▴",
    "Piewerでサーバを自動起動する（推奨）": "Let Piewer start the server (recommended)",
    "準備済み。サーバを起動して有効にします…": "Ready. Starting the server and enabling…",
    "Real-CUGAN を準備しています…（初回はダウンロードに時間がかかります）":
        "Setting up Real-CUGAN… (first time downloads, please wait)",
    "準備に失敗しました: ": "Setup failed: ",
    "（詳細設定で接続先や実行先を確認できます）":
        " (check the endpoint and device under Advanced)",
    "拡大/実行先を変えました。②をもう一度押すと反映されます。":
        "Scale/device changed. Press ② again to apply.",
    "無効です。②を押すと準備して有効にします。":
        "Disabled. Press ② to set up and enable.",
    "✓ 有効（手動の接続先を使用）。": "✓ Enabled (using manual endpoint).",
    "✓ 有効・実行中。小さいページが自動で高解像度化されます。":
        "✓ Enabled and running. Small pages are upscaled automatically.",
    "サーバを起動中…（初回はモデル読込で時間がかかります）":
        "Starting the server… (first run loads the model)",
    "サーバエラー: ": "Server error: ",
    "有効。②を押すとサーバを起動します。": "Enabled. Press ② to start the server.",
    "AI超解像（高解像度化）": "AI Upscale (super-resolution)",
    "🔍 AI超解像の設定を開く…": "🔍 Open AI upscale settings…",
    "有効": "Enabled",
    "無効": "Disabled",
    "このRARを開くには展開ツールが必要ですが、見つかりませんでした。\nPiewer同梱の unrar が読み込めていない可能性があります。\n（ZIP/CBZ形式に変換すると確実に開けます）":
        "Opening this RAR needs an extraction tool, but none was found.\n"
        "The bundled unrar may have failed to load.\n"
        "(Converting it to ZIP/CBZ will always open.)",
    "🏷 この本のタグ": "🏷 Tags on this book",
    "タグを編集…": "Edit tags…",
    "この本からタグを外す": "Remove this tag from the book",
    "タグの管理": "Manage Tags",
    "タグの名前変更・削除ができます（すべての本に反映されます）。":
        "Rename or delete tags (applies to all books).",
    "タグがありません。": "No tags.",
    "タグの名前変更": "Rename Tag",
    "タグの削除": "Delete Tag",
    "新しいタグ名:": "New tag name:",
    "タグ「{tag}」を全ての本から削除しますか？": "Delete the tag “{tag}” from all books?",
    "読み込み中...": "Loading...",
    "ヘルプ・操作一覧": "Help · Controls",

    # ── reader.py: ツールバー / HUD ──
    "← 本棚": "← Shelves",
    "最後": "Last", "次へ": "Next", "前へ": "Prev", "最初": "First",
    "ページ番号": "Page #",
    "このページにしおりを追加 / 解除": "Add / remove bookmark on this page",
    "◀栞": "◀🔖", "栞▶": "🔖▶",
    "しおり ▾": "Bookmarks ▾",
    "しおり一覧（クリックでジャンプ）": "Bookmark list (click to jump)",
    "🗂 目次": "🗂 Pages",
    "全ページのサムネイル一覧から選ぶ": "Pick a page from the thumbnail grid",
    "右→左": "R→L", "見開き": "Spread",
    "奇数始まり": "Odd start", "偶数始まり": "Even start",
    "表紙を単独": "Cover single",
    "1ページ目（表紙）を単独表示し、以降を見開きでペアにする":
        "Show page 1 (cover) alone, then pair the rest as spreads",
    "幅": "Width",
    "シリーズ順": "By series",
    "フィット: ": "Fit: ", "高さ": "Height", "全体": "Whole",
    "表示の合わせ方（高さ / 幅 / 全体）を切り替え": "Cycle fit mode (height / width / whole)",
    "幅に合わせる（ホイールで縦スクロール）": "Fit width (wheel scrolls vertically)",
    "縦読み": "Vertical",
    "縦スクロールの連続表示（Webtoon向け）": "Continuous vertical scroll (Webtoon)",
    "全画面": "Fullscreen",
    "全画面を終了": "Exit fullscreen",
    "🔍 全本棚を検索": "🔍 Search all shelves",
    "📂 登録せず開く": "📂 Open without adding",
    "登録せずに開く": "Open without adding",
    "全本棚を検索": "Search all shelves",
    "検索": "Search",
    "登録できません": "Can't add here",
    "お気に入り・最近読んだ本には直接登録できません。\n通常の本棚に追加してください。":
        "You can't add directly to Favorites or Recently Read.\nPlease add to a normal shelf.",
    "ここには登録できません": "Can't add here",
    "「{name}」へ登録": "Add to “{name}”",
    "🖱  マウスホイール": "🖱  Mouse wheel",
    "拡大・縮小": "Zoom",
    "ページ送り": "Page turn",
    "「ページ送り」では下スクロールで前のページ、上で次のページに進みます。":
        "With “Page turn”, scroll up for the next page and down for the previous page.",
    "ホイール送り": "Wheel turns pages",
    "マウスホイールでページを送る（OFFで拡大縮小）":
        "Mouse wheel turns pages (off = zoom)",
    "右クリックでメニュー表示／ Esc または「← 本棚」で戻る":
        "Right-click for the menu / Esc or “← Shelves” to go back",
    "しおり {n} ▾": "Bookmarks {n} ▾",
    "しおりはありません": "No bookmarks",
    "📑  {n} ページ": "📑  Page {n}",
    "すべてのしおりを削除": "Clear all bookmarks",

    # ── アップデート確認 ──
    "🔄  アップデートを確認": "🔄  Check for updates",
    "最新かどうかを確認します（公式サイトに接続します）。":
        "Check whether a newer version exists (connects to the official site).",
    "アップデート": "Update",
    "最新版です（v{v}）。": "You're on the latest version (v{v}).",
    "新しいバージョン v{v} があります。": "A new version (v{v}) is available.",
    "入手する": "Get it",
    "後で": "Later",
    "アップデートの確認に失敗しました。\nネットワーク接続をご確認ください。":
        "Failed to check for updates.\nPlease check your network connection.",

    # ── 開発を支援（寄付） ──
    "💗  開発を支援": "💗  Support development",
    "Piewer は完全無料・オープンソースです。気に入ったら開発の支援（寄付）をご検討ください。":
        "Piewer is completely free and open source. If you like it, please consider supporting development (a donation).",
    "💗  開発を支援する (Ko-fi)": "💗  Support development (Ko-fi)",
    "データ管理": "Data",
    "操作・ヘルプ": "Controls & Help",

    # ── 画質補正・擬似カラー化（v1.72）──
    "🎨 画質": "🎨 Image",
    "画質補正・擬似カラー化（疑似色刷り）の設定": "Image correction & pseudo-colorization settings",
    "🎨 画質・擬似カラー化": "🎨 Image & Pseudo-color",
    "🎨  画質・擬似カラー化": "🎨  Image & Pseudo-color",
    "🎨  画質補正・擬似カラー化": "🎨  Image correction & pseudo-colorization",
    "画質補正・擬似カラー化を有効にする": "Enable image correction & pseudo-colorization",
    "白黒/カラーのページを見やすく補正し、お好みで“色刷り風”に着色します。":
        "Cleans up black-and-white/color pages and optionally tints them in a 'color-print' style.",
    "画質補正": "Image correction",
    "自動レベル補正（白を白く・黒を黒く）": "Auto level (whiter whites, blacker blacks)",
    "明るさ(ガンマ)": "Brightness (gamma)",
    "シャープ（くっきりさせる）": "Sharpen",
    "擬似カラー化（疑似色刷り）": "Pseudo-colorization (color-print style)",
    "色": "Color",
    "強さ": "Strength",
    "※ 擬似カラー化は“色がついた風”にする処理で、実際の色を再現するものではありません。":
        "* Pseudo-colorization only gives a 'colored' impression; it does not reproduce real colors.",
    "既定に戻す": "Reset to default",
    "なし": "None",
    "セピア": "Sepia",
    "青(2色刷り)": "Blue (2-color)",
    "暖色": "Warm",
    "寒色": "Cool",
    "4色刷り風": "4-color print",
    "色刷り(紺×橙)": "Color print (navy/orange)",
    # ── 分類名の編集（v1.71）──
    "分類名の編集": "Edit category names",
    "✏ 分類名を編集": "✏ Edit category names",
    "ⓘ 命名ルールを表示": "ⓘ Show naming rules",
    "ⓘ 命名ルールを隠す": "ⓘ Hide naming rules",
}
