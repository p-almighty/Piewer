"""ファイル名の構造から自動でタグを抽出する（オフライン・依存なし）。

よくある同人/アーカイブの命名（括弧で要素を区切る方式）を想定する:

    (イベント) [サークル (作者)] タイトル (作品名) [その他]

要素の役割キーは circle / author / parody / event / misc / folder の6種類。
タグにするときの「分類名（接頭辞）」は呼び出し側から `labels` で差し替えられる
（既定は DEFAULT_LABELS）。ユーザーが自分の命名規則に合わせて自由にリネームできる。

純粋関数のみ（config やユーザーデータに一切触れない＝安全にテストできる）。
"""
import re
from pathlib import Path

# タグ種別キー（UIの選択と対応）
T_ARTIST = "artist"   # 作者・サークル
T_PARODY = "parody"   # 原作（パロディ）
T_EVENT = "event"     # イベント・その他
T_FOLDER = "folder"   # 親フォルダ名

# 役割キー → 既定の分類名（接頭辞）。ユーザー設定で上書きできる。
DEFAULT_LABELS = {
    "author": "作者",
    "circle": "サークル",
    "parody": "原作",
    "event": "イベント",
    "folder": "フォルダ",
}

_OP = r"[\(（]"   # 開き括弧（半角/全角）
_CP = r"[\)）]"   # 閉じ括弧
_OB = r"[\[【]"   # 開きブラケット
_CB = r"[\]】]"   # 閉じブラケット

# ブラケット内がこれらを含むなら「その他」扱い（サークルと誤認しない）
_MISC_KEYS = (
    "DL版", "無修正", "修正", "翻訳", "中国", "中國", "简体", "繁体", "韓国", "한국",
    "日本語", "English", "english", "英訳", "英語", "Chinese", "Korean", "カラー",
    "フルカラー", "完全版", "総集編", "単行本", "アンソロジー", "成年コミック", "雑誌",
)


def _merge_labels(labels) -> dict:
    """既定ラベルにユーザー指定（空文字は無視）を重ねた dict を返す。"""
    lab = dict(DEFAULT_LABELS)
    if labels:
        lab.update({k: v for k, v in labels.items() if k in lab and str(v).strip()})
    return lab


def _is_misc(s: str) -> bool:
    return any(k in s for k in _MISC_KEYS)


def parse_name(name: str) -> dict:
    """ファイル名から要素を抽出して dict で返す。

    返り値キー: circle / author / parody(list) / event / misc(list)
    """
    stem = Path(name).stem.strip()
    res = {"circle": None, "author": None, "parody": [], "event": None, "misc": []}

    work = stem
    # 先頭の (…) ＝ イベント
    m = re.match(r"^" + _OP + r"(.+?)" + _CP + r"\s*", work)
    if m:
        res["event"] = m.group(1).strip()
        work = work[m.end():]

    # [...] / 【...】 をすべて取り出して分類
    brackets = re.findall(_OB + r"(.+?)" + _CB, work)
    circle_found = False
    for b in brackets:
        b = b.strip()
        if not b:
            continue
        am = re.match(r"^(.+?)\s*" + _OP + r"(.+?)" + _CP + r"\s*$", b)
        if am and not circle_found:
            res["circle"] = am.group(1).strip()
            res["author"] = am.group(2).strip()
            circle_found = True
        elif _is_misc(b):
            res["misc"].append(b)
        elif not circle_found:
            res["circle"] = b      # 作者表記のないサークルのみブラケット
            circle_found = True
        else:
            res["misc"].append(b)

    # ブラケットを除いて残る (…) ＝ 原作（パロディ）
    work_np = re.sub(_OB + r".+?" + _CB, " ", work)
    for p in re.findall(_OP + r"(.+?)" + _CP, work_np):
        p = p.strip()
        if p and not _is_misc(p):
            res["parody"].append(p)
    return res


def extract_tags(name: str, types, prefixed: bool = True, labels=None) -> list[str]:
    """選択された種別に応じたタグのリストを返す（重複除去・順序維持）。

    types: T_ARTIST / T_PARODY / T_EVENT / T_FOLDER を含む集合。
    prefixed=True なら分類名（既定「作者:」「サークル:」…）を接頭辞として付ける。
    labels: 役割キー→分類名 の上書き（DEFAULT_LABELS を基準にマージ）。
    その他(DL版等)は常にプレーン。
    """
    p = parse_name(name)
    lab = _merge_labels(labels)
    tags: list[str] = []

    def pref(label, val):
        return f"{label}:{val}" if prefixed else val

    if T_ARTIST in types:
        if p["author"]:
            tags.append(pref(lab["author"], p["author"]))
        if p["circle"]:
            tags.append(pref(lab["circle"], p["circle"]))
    if T_PARODY in types:
        for x in p["parody"]:
            tags.append(pref(lab["parody"], x))
    if T_EVENT in types:
        if p["event"]:
            tags.append(pref(lab["event"], p["event"]))
        for x in p["misc"]:
            tags.append(x)   # その他はプレーン
    if T_FOLDER in types:
        parent = Path(name).parent.name      # 親フォルダ名（パスが渡されたとき有効）
        if parent and parent not in (".", "/", "\\"):
            tags.append(pref(lab["folder"], parent))

    seen = set()
    out = []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def propose(books, types, prefixed: bool = True, labels=None):
    """book dict のリストから自動タグ付け案を作る。

    返り値: (mapping, counts)
      mapping: {book_id: [新規に付くタグ,...]}（既存タグに無いものだけ）
      counts:  {タグ: そのタグが付く冊数}（多い順に使う）
    重複 book_id は最初の1回だけ評価する。
    """
    from collections import Counter
    seen = set()
    mapping = {}
    counts = Counter()
    for b in books:
        bid = b.get("id")
        if not bid or bid in seen:
            continue
        seen.add(bid)
        cur = set(b.get("tags", []))
        name = b.get("path") or b.get("title") or ""
        new = [t for t in extract_tags(name, types, prefixed, labels) if t not in cur]
        if new:
            mapping[bid] = new
            for t in new:
                counts[t] += 1
    return mapping, counts


def spec_text(labels=None, lang: str = "ja") -> str:
    """オートタグの命名規則を説明するテキスト（現在の分類名を反映）。UI表示用。"""
    lab = _merge_labels(labels)
    if lang == "en":
        return (
            "Auto-tag reads the structure of the file name and turns each part into a tag.\n\n"
            "Expected pattern:\n"
            "    (event) [circle (author)] title (series) [other]\n\n"
            "Example:\n"
            "    (EventName) [CircleName (AuthorName)] My Title (SeriesName) [extra]\n"
            "      -> {author}:AuthorName / {circle}:CircleName / {parody}:SeriesName /\n"
            "         {event}:EventName / extra\n\n"
            "Rules:\n"
            "  - Leading (...) = event.\n"
            "  - [name (name)] = circle (author). A lone [name] = circle.\n"
            "  - (...) after the brackets = parody / original series.\n"
            "  - Keywords like DL版 / 無修正 / English become plain 'other' tags.\n\n"
            "The category names ({author} / {circle} / {parody} / {event} / folder)\n"
            "can be renamed to fit your own file naming."
        ).format(**lab)
    return (
        "オートタグはファイル名の構造を読み取り、各要素をタグにします。\n\n"
        "想定する命名パターン:\n"
        "    (イベント) [サークル (作者)] タイトル (作品名) [その他]\n\n"
        "例:\n"
        "    (イベント名) [サークル名 (作者名)] 作品タイトル (シリーズ名) [おまけ]\n"
        "      → {author}:作者名 ／ {circle}:サークル名 ／ {parody}:シリーズ名 ／\n"
        "         {event}:イベント名 ／ おまけ\n\n"
        "ルール:\n"
        "  ・先頭の (…) ＝ イベント\n"
        "  ・[名前 (名前)] ＝ サークル (作者)。括弧なしの [名前] はサークル\n"
        "  ・括弧の後ろの (…) ＝ 原作（作品名）\n"
        "  ・DL版・無修正・English などのキーワードは接頭辞なしの「その他」タグ\n\n"
        "分類名（{author} ／ {circle} ／ {parody} ／ {event} ／ フォルダ）は、\n"
        "自分のファイル命名に合わせて自由にリネームできます。"
    ).format(**lab)
