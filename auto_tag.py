"""ファイル名から自動タグを抽出する（同人標準命名規則ベース・オフライン・依存なし）。

対応する命名: `(イベント) [サークル (作者)] タイトル (原作) [その他]`
- 例: (#イベント名) [サークル名 (作者名)] 作品タイトル… (シリーズ名) [DL版]
      → 作者:作者名 / サークル:サークル名 / 原作:シリーズ名 / イベント:#イベント名 / DL版

純粋関数のみ（config やユーザーデータに一切触れない＝安全にテストできる）。
"""
import re
from pathlib import Path

# タグ種別キー（UIの選択と対応）
T_ARTIST = "artist"   # 作者・サークル
T_PARODY = "parody"   # 原作（パロディ）
T_EVENT = "event"     # イベント・その他
T_FOLDER = "folder"   # 親フォルダ名

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


def extract_tags(name: str, types, prefixed: bool = True) -> list[str]:
    """選択された種別に応じたタグのリストを返す（重複除去・順序維持）。

    types: T_ARTIST / T_PARODY / T_EVENT を含む集合。
    prefixed=True なら「作者:」「サークル:」「原作:」「イベント:」を付ける。
    その他(DL版等)は常にプレーン。
    """
    p = parse_name(name)
    tags: list[str] = []

    def pref(label, val):
        return f"{label}:{val}" if prefixed else val

    if T_ARTIST in types:
        if p["author"]:
            tags.append(pref("作者", p["author"]))
        if p["circle"]:
            tags.append(pref("サークル", p["circle"]))
    if T_PARODY in types:
        for x in p["parody"]:
            tags.append(pref("原作", x))
    if T_EVENT in types:
        if p["event"]:
            tags.append(pref("イベント", p["event"]))
        for x in p["misc"]:
            tags.append(x)   # その他はプレーン
    if T_FOLDER in types:
        parent = Path(name).parent.name      # 親フォルダ名（パスが渡されたとき有効）
        if parent and parent not in (".", "/", "\\"):
            tags.append(pref("フォルダ", parent))

    seen = set()
    out = []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def propose(books, types, prefixed: bool = True):
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
        new = [t for t in extract_tags(name, types, prefixed) if t not in cur]
        if new:
            mapping[bid] = new
            for t in new:
                counts[t] += 1
    return mapping, counts
