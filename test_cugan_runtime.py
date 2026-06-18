"""ai_runtime の Real-CUGAN 取得ロジックのテスト（ネットワーク不要・file://で実DL）。

RUNTIME_DIR を一時dirへ隔離。重み名マッピング・準備判定・zip展開/重み配置を、
file:// URL を使って実際の download 関数で検証する（実データに触れない）。
"""
import io
import sys
import zipfile
import tempfile
import urllib.request
from pathlib import Path

import ai_runtime

TMP = Path(tempfile.mkdtemp(prefix="piewer_cugan_rt_"))
ai_runtime.set_base_dir(TMP / "runtime")

_fails = []


def check(cond, msg):
    print(f"[{'OK' if cond else 'NG'}] {msg}")
    if not cond:
        _fails.append(msg)


def as_file_url(p: Path) -> str:
    return urllib.parse.urljoin("file:", urllib.request.pathname2url(str(p)))


import urllib.parse  # noqa: E402


def main():
    # ① 重み名マッピング（サーバ側と一致）
    check(ai_runtime.cugan_weight_filename(2, 1) == "up2x-latest-denoise1x.pth",
          "weight_filename: 2x/denoise1")
    check(ai_runtime.cugan_weight_filename(2, -1) == "up2x-latest-conservative.pth",
          "weight_filename: conservative")
    check(ai_runtime.cugan_weight_filename(4, 3) == "up4x-latest-denoise3x.pth",
          "weight_filename: 4x/denoise3")
    check(ai_runtime.cugan_weight_filename(4, 1) == "up4x-latest-denoise3x.pth",
          "weight_filename: 4xのdenoise1→denoise3x（存在する方へ）")
    check(ai_runtime.cugan_weight_filename(3, 2) == "up3x-latest-denoise3x.pth",
          "weight_filename: 3xのdenoise2→denoise3x")
    check(ai_runtime.cugan_weight_filename(2, 2) == "up2x-latest-denoise2x.pth",
          "weight_filename: 2xは5種そのまま")

    # ② 初期は未準備
    check(ai_runtime.cugan_repo_ready() is False, "repo未取得は False")
    check(ai_runtime.cugan_weights_ready(2, 1) is False, "weights未取得は False")
    # python/deps が無いので cugan_ready は False（repo/weightsを置いても）
    check(ai_runtime.cugan_ready(2, 1) is False, "python/deps無しなら cugan_ready False")

    # ③ repo（単一ファイル upcunet_v3.py）を file:// から実取得
    pysrc = TMP / "upcunet_v3.py"
    pysrc.write_text("# fake RealWaifuUpScaler\n", encoding="utf-8")
    ai_runtime.CUGAN_REPO_URL = as_file_url(pysrc)
    ok = ai_runtime.download_cugan_repo()
    check(ok and ai_runtime.cugan_repo_ready(),
          "download_cugan_repo: 単一ファイルを配置")
    check((ai_runtime.cugan_repo_dir() / "upcunet_v3.py").exists(),
          "repo配置先に upcunet_v3.py がある")
    # 2回目はスキップ（既存）
    check(ai_runtime.download_cugan_repo() is True, "download_cugan_repo: 既存はスキップ")

    # ④ 重みを file:// から実取得
    wsrc = TMP / "src_weight.pth"
    wsrc.write_bytes(b"PTHWEIGHTDATA" * 100)
    ai_runtime.CUGAN_WEIGHTS_BASE = as_file_url(TMP) + "/"  # <TMP>/<filename>
    # ファイル名を (2,1) のものに合わせて用意
    (TMP / ai_runtime.cugan_weight_filename(2, 1)).write_bytes(b"W" * 500)
    ok = ai_runtime.download_cugan_weight(2, 1)
    check(ok and ai_runtime.cugan_weights_ready(2, 1),
          "download_cugan_weight: 配置→ready")
    # 別の (scale,denoise) はまだ無い
    check(ai_runtime.cugan_weights_ready(4, 1) is False, "別設定の重みは未準備")

    # ⑤ status dict
    st = ai_runtime.cugan_status(2, 1)
    check(st["repo"] is True and st["weights"] is True
          and st["python"] is False, "cugan_status: 各要素を反映")

    print("-" * 40)
    if _fails:
        print(f"FAILED: {len(_fails)} -> {_fails}"); sys.exit(1)
    print(f"ALL PASSED  (tmp={TMP})")


if __name__ == "__main__":
    main()
