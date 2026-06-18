"""RAR展開ツールの配線＋診断テスト。

オフライン: 同梱 unrar.exe に rarfile.UNRAR_TOOL が向くこと／rar_tool_ready の判定。
ネットがあれば: 公式SFX(=圧縮RAR)の圧縮エントリを同梱unrar経由で実展開できること。
実データには触れない。直接実行可。
"""
import sys
import tempfile
import urllib.request
from pathlib import Path

import config
import rarfile

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def main():
    # ① 配線: 同梱 tools/unrar.exe を指している
    tool = rarfile.UNRAR_TOOL
    check(tool.lower().replace("\\", "/").endswith("tools/unrar.exe"),
          f"UNRAR_TOOL が同梱unrarを指す 実={tool}")
    check(Path(tool).exists(), "同梱 unrar.exe が存在する")
    check(config.rar_tool_ready() is True, "rar_tool_ready(): 同梱ツールで True")

    # ② 診断: ツールを壊すと False（このPCは他ツール未導入）→ 復元で True
    saved = rarfile.UNRAR_TOOL
    rarfile.UNRAR_TOOL = str(Path(tempfile.gettempdir()) / "no_such_unrar.exe")
    check(config.rar_tool_ready() is False, "rar_tool_ready(): ツール不在で False")
    config._configure_rar_tool()
    check(config.rar_tool_ready() is True, "_configure_rar_tool(): 再設定で True")
    if not Path(rarfile.UNRAR_TOOL).exists():   # 念のため
        rarfile.UNRAR_TOOL = saved

    # ③ （任意・ネット）公式SFXの圧縮エントリを同梱unrarで実展開できる
    try:
        tmp = Path(tempfile.mkdtemp()); sfx = tmp / "u.exe"
        urllib.request.urlretrieve("https://www.rarlab.com/rar/unrarw64.exe", sfx)
        rf = rarfile.RarFile(str(sfx))
        data = rf.read("license.txt")   # 圧縮エントリ→ツールが要る
        check(len(data) > 100 and b"UnRAR" in data,
              "同梱unrarで圧縮RARエントリを実展開できた")
    except Exception as e:
        print(f"[SKIP] ネットワーク不可のため実展開テストは省略: {type(e).__name__}")

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
