"""AI着色ランタイムの自動構築（フェーズB）。

ユーザーが何も手で用意しなくても、Piewer が `~/.manga_viewer/ai_runtime/` に
着色サーバを動かすための一式をダウンロード／展開する:

  ai_runtime/
    python/   ── standalone Python（python-build-standalone・単体で動く）
    repo/     ── manga-colorization-v2（着色プログラム本体）
    state.json ─ どのステップまで完了したか（再開用）

重い依存（torch 等）はこの runtime の中だけに入り、Piewer 本体はスリムなまま。
重み（モデルファイル）は作者の Google Drive から各自DL（ミラー/同梱はライセンス上不可）。

構築は4ステップ:
  1. python   ── standalone Python を取得・展開
  2. deps     ── その Python に torch / torchvision / opencv / scikit-image を pip install
  3. repo     ── manga-colorization-v2 のソースを取得・展開
  4. weights  ── generator.zip / net_rgb.pth を Google Drive から取得して配置

各ステップは完了マーカー（state.json と実ファイルの存在）で再開できる。device(cuda/cpu)が
変わると deps だけ入れ直す（CUDA版↔CPU版でwheelが違うため）。
"""
import os
import re
import json
import shutil
import zipfile
import tarfile
import threading
import subprocess
import urllib.request
import urllib.parse
import http.cookiejar
from pathlib import Path

from PySide6.QtCore import QObject, Signal

import config

# ── 配置（保存先は変更可能。set_base_dir で差し替える）──────────
# 既定は ~/.manga_viewer/ai_runtime/。torch等で数GBになるため、別ドライブへ移せる。
SUBDIR_NAME = "Piewer_ai_runtime"   # 任意フォルダ配下に作る名前付きサブフォルダ


def default_base_dir() -> Path:
    return config.APP_DIR / "ai_runtime"


RUNTIME_DIR = default_base_dir()
PYTHON_DIR = RUNTIME_DIR / "python"
REPO_DIR = RUNTIME_DIR / "repo"
STATE_FILE = RUNTIME_DIR / "state.json"


def _recompute():
    global PYTHON_DIR, REPO_DIR, STATE_FILE
    PYTHON_DIR = RUNTIME_DIR / "python"
    REPO_DIR = RUNTIME_DIR / "repo"
    STATE_FILE = RUNTIME_DIR / "state.json"


def base_dir() -> Path:
    return RUNTIME_DIR


def set_base_dir(path) -> None:
    """保存先（RUNTIME_DIR）を切り替える。空指定で既定へ戻す。ファイル移動はしない。"""
    global RUNTIME_DIR
    RUNTIME_DIR = Path(path) if path else default_base_dir()
    _recompute()


def move_base_dir(new_path) -> bool:
    """既存の構築物を新しい保存先へ移動して切り替える。移動先が空でないと失敗。"""
    return move_base_dir_progress(new_path)


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def move_base_dir_progress(new_path, progress_cb=None, is_cancelled=None) -> bool:
    """既存の構築物を新しい保存先へ移動して切り替える（進捗・中止対応）。

    同一ドライブなら rename で一瞬。別ドライブはファイルをチャンクコピーしながら
    progress_cb(done_bytes, total_bytes) を呼び、完了後に元を削除する。
    移動先が空でない場合・中止された場合は False（切り替えない）。
    """
    new = Path(new_path)
    old = RUNTIME_DIR
    try:
        if old.resolve() == new.resolve():
            return True
    except Exception:
        pass
    if not old.exists():
        set_base_dir(new)
        return True
    if new.exists() and any(new.iterdir()):
        return False   # 移動先が既に使われている
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    # 同一ボリュームなら rename（瞬時・コピー不要）
    try:
        os.rename(old, new)
        set_base_dir(new)
        return True
    except OSError:
        pass   # 別ボリューム等 → チャンクコピーへ
    # 別ドライブ: ファイルをコピーしながら進捗通知
    total = _dir_size(old)
    done = 0
    try:
        for root, _dirs, files in os.walk(old):
            rel = os.path.relpath(root, old)
            dst_root = new if rel == "." else new / rel
            dst_root.mkdir(parents=True, exist_ok=True)
            for fn in files:
                if is_cancelled and is_cancelled():
                    shutil.rmtree(new, ignore_errors=True)
                    return False
                src = os.path.join(root, fn)
                dst = dst_root / fn
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    while True:
                        if is_cancelled and is_cancelled():
                            fo.close()
                            shutil.rmtree(new, ignore_errors=True)
                            return False
                        chunk = fi.read(1024 * 512)
                        if not chunk:
                            break
                        fo.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
                shutil.copymode(src, dst)
        shutil.rmtree(old, ignore_errors=True)
        set_base_dir(new)
        return True
    except Exception:
        shutil.rmtree(new, ignore_errors=True)
        return False

# ── 取得元（更新時はここだけ直す）────────────────────────────
# standalone Python（python-build-standalone・install_only 版＝展開してすぐ動く）。
# 展開するとトップに python/ ディレクトリができ、中に python.exe がある。
PY_VER = "3.12.7"
PY_TAG = "20241016"
PY_ASSET = f"cpython-{PY_VER}+{PY_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"
PYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PY_TAG}/{PY_ASSET}"
)

# 着色プログラム本体（GitHub zip。git 不要）。
REPO_URL = "https://github.com/qweasdd/manga-colorization-v2/archive/refs/heads/master.zip"

# pip で入れる依存。torch/torchvision は専用indexから、他はPyPIから。
TORCH_PKGS = ["torch==2.6.0", "torchvision==0.21.0"]
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu124",
    "cpu": "https://download.pytorch.org/whl/cpu",
}
EXTRA_PKGS = ["opencv-python", "scikit-image"]

# 重み（作者 Google Drive）。file_id → リポジトリ内の配置先（REPO_DIR 相対）。
WEIGHTS = [
    ("1qmxUEKADkEM4iYLp1fpPLLKnfZ6tcF-t", "networks/generator.zip", "generator（生成器・約128MB）"),
    ("161oyQcYpdkVdw8gKz_MA8RD-Wtg9XDp3", "denoising/models/net_rgb.pth", "denoiser（ノイズ除去・約3MB）"),
]

STEPS = [
    ("python", "実行用 Python"),
    ("deps", "AIライブラリ（torch 等）"),
    ("repo", "着色プログラム"),
    ("weights", "モデルデータ（重み）"),
]

# ── Real-CUGAN（超解像）取得元（更新時はここだけ直す）────────────
# 超解像は着色と同じ python/torch を流用する（深い依存の再導入は不要）。追加で要るのは
# 推論コード（upcunet_v3.py・torch/numpy/cv2のみで自己完結＝1ファイル）と、
# 拡大率/ノイズ除去ごとの重み(.pth)だけ。更新時はこの2つのURLを直す。
CUGAN_REPO_URL = ("https://raw.githubusercontent.com/bilibili/ailab/main/"
                  "Real-CUGAN/upcunet_v3.py")
# 重み: <base>/<filename> でDL（HuggingFaceのミラー・weights_v3）。
CUGAN_WEIGHTS_BASE = ("https://huggingface.co/spaces/DianXian/Real-CUGAN/"
                      "resolve/main/weights_v3/")
# denoise 値 → Real-CUGAN の重みファイル名サフィックス（local_upscale_server と一致させる）
_CUGAN_DENOISE_SUFFIX = {-1: "conservative", 0: "no-denoise",
                         1: "denoise1x", 2: "denoise2x", 3: "denoise3x"}


# ── パス / 状態の問い合わせ ──────────────────────────────────

def runtime_python_exe() -> Path:
    return PYTHON_DIR / "python.exe"


def runtime_repo_dir() -> Path:
    return REPO_DIR


def gdrive_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def _weight_dest(rel: str) -> Path:
    return REPO_DIR / rel


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def python_ready() -> bool:
    return runtime_python_exe().exists()


def deps_ready(device: str = "") -> bool:
    """依存が入っているか。device指定時はその種別で入っているかも見る。"""
    st = _load_state()
    if not st.get("deps"):
        return False
    if device and st.get("deps_device") and st["deps_device"] != device:
        return False
    return True


def repo_ready() -> bool:
    return (REPO_DIR / "colorizator.py").exists()


def weights_ready() -> bool:
    return all(_weight_dest(rel).exists() and _weight_dest(rel).stat().st_size > 0
               for _fid, rel, _label in WEIGHTS)


def is_ready(device: str = "") -> bool:
    """着色サーバを起動できる状態か（4ステップ全部そろっている）。"""
    return python_ready() and deps_ready(device) and repo_ready() and weights_ready()


def status(device: str = "") -> dict:
    """各ステップの完了状況。UIのチェック表示用。"""
    return {
        "python": python_ready(),
        "deps": deps_ready(device),
        "repo": repo_ready(),
        "weights": weights_ready(),
    }


# ── Real-CUGAN（超解像）資産のパス / 準備状況 ──────────────────

def cugan_dir() -> Path:
    return RUNTIME_DIR / "cugan"


def cugan_repo_dir() -> Path:
    return cugan_dir() / "repo"


def cugan_weights_dir() -> Path:
    return cugan_dir() / "weights"


def cugan_weight_filename(scale: int, denoise: int) -> str:
    """(scale, denoise) に対応する Real-CUGAN の標準重みファイル名。

    3x/4x には denoise1x/denoise2x が存在しない（公式weights_v3）ため、その指定は
    用意のある denoise3x へ寄せる。2x は5種すべてある。
    """
    suffix = _CUGAN_DENOISE_SUFFIX.get(int(denoise), "denoise1x")
    if int(scale) >= 3 and suffix in ("denoise1x", "denoise2x"):
        suffix = "denoise3x"
    return f"up{int(scale)}x-latest-{suffix}.pth"


def cugan_repo_ready() -> bool:
    return (cugan_repo_dir() / "upcunet_v3.py").exists()


def cugan_weight_path(scale: int, denoise: int) -> Path:
    return cugan_weights_dir() / cugan_weight_filename(scale, denoise)


def cugan_weights_ready(scale: int = 2, denoise: int = 1) -> bool:
    p = cugan_weight_path(scale, denoise)
    return p.exists() and p.stat().st_size > 0


def cugan_ready(scale: int = 2, denoise: int = 1) -> bool:
    """超解像サーバ(cugan)を起動できる状態か（python＋torch＋コード＋重み）。"""
    return (python_ready() and deps_ready() and cugan_repo_ready()
            and cugan_weights_ready(scale, denoise))


def cugan_status(scale: int = 2, denoise: int = 1) -> dict:
    """超解像構築の各要素の状況（UI表示用）。python/deps は着色と共用。"""
    return {
        "python": python_ready(),
        "deps": deps_ready(),
        "repo": cugan_repo_ready(),
        "weights": cugan_weights_ready(scale, denoise),
    }


def remove_runtime() -> bool:
    """構築物を丸ごと削除（作り直し用）。"""
    try:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
        return not RUNTIME_DIR.exists()
    except Exception:
        return False


class BuildCancelled(Exception):
    pass


# ── ビルダー本体 ────────────────────────────────────────────

class RuntimeBuilder(QObject):
    """ランタイムをバックグラウンドスレッドで構築する。進捗はsignalで通知。"""

    # step_key, status("running"/"done"/"error"/"skipped"), message
    step_status = Signal(str, str, str)
    # 0..100、不定のときは -1
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(bool, str)   # 全体の成否, メッセージ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancel = True
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def start(self, device: str = "cpu", steps: list[str] | None = None):
        """構築を開始（非ブロッキング）。steps省略時は未完了の全ステップ。"""
        if self.is_running():
            return
        self._cancel = False
        self._thread = threading.Thread(
            target=self._run, args=(device, steps), daemon=True)
        self._thread.start()

    # ── 進行 ────────────────────────────────────────────────

    def _check_cancel(self):
        if self._cancel:
            raise BuildCancelled()

    def _run(self, device: str, steps):
        try:
            todo = steps if steps else [k for k, _ in STEPS]
            for key, _label in STEPS:
                if key not in todo:
                    continue
                self._check_cancel()
                if key == "python":
                    self._do_python()
                elif key == "deps":
                    self._do_deps(device)
                elif key == "repo":
                    self._do_repo()
                elif key == "weights":
                    self._do_weights()
            self.finished.emit(True, "AI着色の準備が完了しました。")
        except BuildCancelled:
            self.step_status.emit("", "error", "中止しました")
            self.finished.emit(False, "構築を中止しました。")
        except Exception as e:
            self.finished.emit(False, f"構築に失敗しました: {e}")

    # ── ① Python ───────────────────────────────────────────

    def _do_python(self):
        if python_ready():
            self.step_status.emit("python", "skipped", "導入済み")
            return
        self.step_status.emit("python", "running", "Python をダウンロード中…")
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = RUNTIME_DIR / "_python.tar.gz"
        self._download(PYTHON_URL, tmp, "Python")
        self._check_cancel()
        self.progress.emit(-1)
        self.step_status.emit("python", "running", "展開中…")
        # tar の中身はトップに python/ がある。RUNTIME_DIR へ展開すると PYTHON_DIR になる。
        if PYTHON_DIR.exists():
            shutil.rmtree(PYTHON_DIR, ignore_errors=True)
        with tarfile.open(tmp, "r:gz") as tar:
            tar.extractall(RUNTIME_DIR)
        try:
            tmp.unlink()
        except Exception:
            pass
        if not python_ready():
            raise RuntimeError("Python の展開後に python.exe が見つかりません")
        self._mark("python", True)
        self.step_status.emit("python", "done", f"完了（Python {PY_VER}）")

    # ── ② 依存（pip）────────────────────────────────────────

    def _do_deps(self, device: str):
        if deps_ready(device):
            self.step_status.emit("deps", "skipped", "導入済み")
            return
        if not python_ready():
            raise RuntimeError("先に Python の導入が必要です")
        py = str(runtime_python_exe())
        idx = TORCH_INDEX.get(device, TORCH_INDEX["cpu"])
        kind = "GPU(CUDA)版" if device == "cuda" else "CPU版"
        self.step_status.emit("deps", "running", f"pip を更新中… ({kind})")
        self._pip(py, ["install", "--upgrade", "pip"])
        self._check_cancel()
        self.step_status.emit("deps", "running",
                              f"torch をインストール中…（{kind}・大きいので時間がかかります）")
        self._pip(py, ["install", "--timeout", "1000", "--retries", "5",
                       "--index-url", idx, *TORCH_PKGS])
        self._check_cancel()
        self.step_status.emit("deps", "running", "opencv / scikit-image をインストール中…")
        self._pip(py, ["install", "--timeout", "1000", "--retries", "5", *EXTRA_PKGS])
        self._check_cancel()
        st = _load_state()
        st["deps"] = True
        st["deps_device"] = device
        _save_state(st)
        self.step_status.emit("deps", "done", f"完了（{kind}）")

    def _pip(self, py: str, args: list[str]):
        cmd = [py, "-m", "pip", *args]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW   # コンソールを出さない
        self.progress.emit(-1)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=flags)
        try:
            for line in self._proc.stdout:   # 1行ずつログへ
                if self._cancel:
                    break
                line = line.rstrip()
                if line:
                    self.log.emit(line)
            self._proc.wait()
        finally:
            rc = self._proc.returncode
            self._proc = None
        self._check_cancel()
        if rc not in (0, None):
            raise RuntimeError(f"pip が失敗しました (終了コード {rc})。ログを確認してください。")

    # ── ③ リポジトリ ────────────────────────────────────────

    def _do_repo(self):
        if repo_ready():
            self.step_status.emit("repo", "skipped", "取得済み")
            return
        self.step_status.emit("repo", "running", "着色プログラムをダウンロード中…")
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = RUNTIME_DIR / "_repo.zip"
        self._download(REPO_URL, tmp, "リポジトリ")
        self._check_cancel()
        self.progress.emit(-1)
        self.step_status.emit("repo", "running", "展開中…")
        if REPO_DIR.exists():
            shutil.rmtree(REPO_DIR, ignore_errors=True)
        # zip のトップは manga-colorization-v2-master/ なので、その中身を REPO_DIR へ移す。
        extract_to = RUNTIME_DIR / "_repo_x"
        if extract_to.exists():
            shutil.rmtree(extract_to, ignore_errors=True)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(extract_to)
        subdirs = [p for p in extract_to.iterdir() if p.is_dir()]
        src = subdirs[0] if len(subdirs) == 1 else extract_to
        shutil.move(str(src), str(REPO_DIR))
        for junk in (tmp, extract_to):
            try:
                if junk.is_dir():
                    shutil.rmtree(junk, ignore_errors=True)
                else:
                    junk.unlink()
            except Exception:
                pass
        if not repo_ready():
            raise RuntimeError("リポジトリ展開後に colorizator.py が見つかりません")
        # 重みの配置先フォルダを用意しておく
        (REPO_DIR / "networks").mkdir(parents=True, exist_ok=True)
        (REPO_DIR / "denoising" / "models").mkdir(parents=True, exist_ok=True)
        self._mark("repo", True)
        self.step_status.emit("repo", "done", "完了")

    # ── ④ 重み（Google Drive）──────────────────────────────

    def _do_weights(self):
        if weights_ready():
            self.step_status.emit("weights", "skipped", "配置済み")
            return
        if not repo_ready():
            raise RuntimeError("先に着色プログラムの取得が必要です")
        for fid, rel, label in WEIGHTS:
            self._check_cancel()
            dest = _weight_dest(rel)
            if dest.exists() and dest.stat().st_size > 0:
                continue
            self.step_status.emit("weights", "running", f"{label} をダウンロード中…")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                gdrive_download(fid, dest, self._on_dl_progress, self._is_cancelled)
            except BuildCancelled:
                raise
            except Exception as e:
                raise RuntimeError(
                    f"{label} の自動ダウンロードに失敗しました（{e}）。"
                    "「重みを手動で配置」から入手してください。")
            if not dest.exists() or dest.stat().st_size == 0:
                raise RuntimeError(f"{label} のダウンロードに失敗しました。")
        self._mark("weights", True)
        self.step_status.emit("weights", "done", "完了")

    def place_weight_file(self, index: int, src_path: str) -> bool:
        """手動DLしたファイルを所定の場所へコピー（手動フォールバック用）。"""
        try:
            fid, rel, _label = WEIGHTS[index]
            dest = _weight_dest(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dest)
            if weights_ready():
                self._mark("weights", True)
            return dest.exists() and dest.stat().st_size > 0
        except Exception:
            return False

    # ── 共通ヘルパ ─────────────────────────────────────────

    def _is_cancelled(self) -> bool:
        return self._cancel

    def _on_dl_progress(self, done: int, total: int):
        if total > 0:
            self.progress.emit(int(done * 100 / total))
        else:
            self.progress.emit(-1)

    def _download(self, url: str, dest: Path, label: str):
        """進捗付きダウンロード（urllib）。キャンセル対応。"""
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            done = 0
            with open(dest, "wb") as f:
                while True:
                    self._check_cancel()
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    self._on_dl_progress(done, total)

    def _mark(self, key: str, ok: bool):
        st = _load_state()
        st[key] = ok
        _save_state(st)


# ── Google Drive ダウンロード（確認トークン対応・pure python）──

def gdrive_download(file_id: str, dest: Path, progress_cb=None, is_cancelled=None):
    """Google Drive の共有ファイルをダウンロードする。

    大きいファイルは「ウイルススキャンできません」確認ページが返るので、その HTML から
    隠しフォーム（action と hidden input）を読み取って本ダウンロードURLを組み立てる。
    gdown 等の外部依存なしで動かすための最小実装。
    """
    base = "https://drive.usercontent.google.com/download"
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]

    params = {"id": file_id, "export": "download"}
    url = base + "?" + urllib.parse.urlencode(params)

    for _attempt in range(3):
        resp = opener.open(url, timeout=60)
        ctype = resp.headers.get("Content-Type", "")
        if "text/html" not in ctype:
            # そのまま本体。ストリーム保存。
            _stream_to_file(resp, dest, progress_cb, is_cancelled)
            return
        # 確認ページ。フォームを解析して本ダウンロードURLを作る。
        html = resp.read().decode("utf-8", "ignore")
        action = re.search(r'action="([^"]+)"', html)
        if not action:
            raise RuntimeError("確認ページの解析に失敗しました")
        form_url = action.group(1).replace("&amp;", "&")
        hidden = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', html))
        if not hidden:
            raise RuntimeError("確認トークンが見つかりませんでした")
        url = form_url + "?" + urllib.parse.urlencode(hidden)
    # 最後の url で本体を取りに行く
    resp = opener.open(url, timeout=60)
    _stream_to_file(resp, dest, progress_cb, is_cancelled)


def _stream_to_file(resp, dest: Path, progress_cb, is_cancelled):
    total = int(resp.headers.get("Content-Length", 0) or 0)
    done = 0
    with open(dest, "wb") as f:
        while True:
            if is_cancelled and is_cancelled():
                raise BuildCancelled()
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total)


# ── Real-CUGAN（超解像）資産のダウンロード ──────────────────────

def _http_download(url: str, dest: Path, progress_cb=None, is_cancelled=None):
    """進捗付きHTTPダウンロード（urllib・キャンセル対応）。重い依存なし。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        _stream_to_file(resp, dest, progress_cb, is_cancelled)


def download_cugan_repo(progress_cb=None, is_cancelled=None) -> bool:
    """Real-CUGAN の推論コード(upcunet_v3.py)を cugan/repo に配置（既存ならスキップ）。

    upcunet_v3.py は torch/numpy/cv2 だけで動く単一ファイルなので、リポジトリ全体では
    なくこの1ファイルだけを取得する（cv2 は着色ランタイムの opencv-python を流用）。
    """
    if cugan_repo_ready():
        return True
    cugan_repo_dir().mkdir(parents=True, exist_ok=True)
    dest = cugan_repo_dir() / "upcunet_v3.py"
    _http_download(CUGAN_REPO_URL, dest, progress_cb, is_cancelled)
    if not cugan_repo_ready():
        raise RuntimeError("Real-CUGAN の推論コード(upcunet_v3.py)の取得に失敗しました")
    return True


def download_cugan_weight(scale: int = 2, denoise: int = 1,
                          progress_cb=None, is_cancelled=None) -> bool:
    """指定 (scale, denoise) の重みを取得して cugan/weights に配置（既存ならスキップ）。"""
    if cugan_weights_ready(scale, denoise):
        return True
    cugan_weights_dir().mkdir(parents=True, exist_ok=True)
    fname = cugan_weight_filename(scale, denoise)
    dest = cugan_weight_path(scale, denoise)
    _http_download(CUGAN_WEIGHTS_BASE + fname, dest, progress_cb, is_cancelled)
    if not (dest.exists() and dest.stat().st_size > 0):
        raise RuntimeError(f"重み {fname} のダウンロードに失敗しました")
    return True
