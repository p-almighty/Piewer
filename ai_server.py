"""ローカル着色サーバの生存管理（フェーズA）。

Piewer が tools/local_color_server.py を子プロセスとして起動/停止する。これにより
ユーザーは「ターミナルでコマンドを打つ」必要がなくなる（ランタイムさえあれば）。
重い依存(torch等)はその子プロセス側にあり、Piewer本体には入らない。

将来（フェーズB）は python/repo/重み を ~/.manga_viewer/ai_runtime へ自動構築し、
ここへ渡す。今は設定で python と repo のパスを指定する。
"""
import os
import sys
import socket
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


def default_server_script() -> str:
    """同梱の着色サーバスクリプトのパス（dev=本体隣 / frozen=_MEIPASS）。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "")) or Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return str(base / "tools" / "local_color_server.py")


def has_nvidia_gpu() -> bool:
    """nvidia-smi があり、GPUが1台以上見えるか（CPU/GPU既定の判定用）。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "-L"], capture_output=True, timeout=5)
        return out.returncode == 0 and b"GPU" in out.stdout
    except Exception:
        return False


def port_available(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class ColorServerManager(QObject):
    """着色サーバの起動/停止を管理する。状態は status_changed で通知。"""

    status_changed = Signal(str, str)   # (status, message)

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

    def __init__(self):
        super().__init__()
        self._proc: QProcess | None = None
        self._status = self.STOPPED
        self._msg = ""
        self._port = 0
        self._device = "cpu"
        self._stderr = b""
        self._stopping = False
        self._waited = 0
        self._ready = QTimer(self); self._ready.setInterval(700)
        self._ready.timeout.connect(self._check_ready)

    # ── 状態 ────────────────────────────────────────────────

    @property
    def status(self) -> str: return self._status
    @property
    def message(self) -> str: return self._msg
    @property
    def device(self) -> str: return self._device

    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self._port}/colorize" if self._port else ""

    def is_running(self) -> bool:
        return self._status == self.RUNNING

    def is_active(self) -> bool:
        return self._status in (self.STARTING, self.RUNNING)

    def _set(self, status: str, msg: str = ""):
        self._status = status; self._msg = msg
        self.status_changed.emit(status, msg)

    # ── 起動 / 停止 ─────────────────────────────────────────

    def start(self, python: str, repo: str, device: str = "cpu", port: int = 7860,
              saturation: float = 1.0, server_script: str = ""):
        if self.is_active():
            return
        script = server_script or default_server_script()
        checks = [("Python", python), ("着色サーバ", script), ("モデルのフォルダ", repo)]
        for label, p in checks:
            if not p or not Path(p).exists():
                self._set(self.ERROR, f"{label} が見つかりません: {p}")
                return
        if not port_available(port):
            self._set(self.ERROR, f"ポート {port} が使用中です。設定で別のポートにしてください。")
            return
        self._port = port
        self._device = device
        self._stderr = b""
        self._stopping = False
        args = [script, "--backend", "manga2", "--repo", repo,
                "--device", device, "--port", str(port)]
        if abs(float(saturation) - 1.0) > 0.01:
            args += ["--saturation", str(saturation)]
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._set(self.STARTING, f"起動中… (port {port} / {device})")
        self._proc.start(python, args)
        self._waited = 0
        self._ready.start()

    def stop(self):
        self._ready.stop()
        self._stopping = True
        if self._proc is not None:
            try:
                self._proc.terminate()
                if not self._proc.waitForFinished(3000):
                    self._proc.kill(); self._proc.waitForFinished(2000)
            except Exception:
                pass
            self._proc = None
        self._port = 0
        self._set(self.STOPPED, "")

    # ── 内部 ────────────────────────────────────────────────

    def _on_stderr(self):
        if self._proc is None:
            return
        try:
            self._stderr += bytes(self._proc.readAllStandardError())
        except Exception:
            pass

    def _on_proc_error(self, *_):
        if self._stopping:
            return
        self._fail("プロセスを起動できませんでした（Python のパスを確認してください）")

    def _on_finished(self, *_):
        if self._stopping:
            return
        # 起動完了前/稼働中に終了＝失敗とみなす
        tail = self._stderr.decode("utf-8", "ignore").strip().splitlines()
        msg = tail[-1] if tail else "サーバが終了しました"
        self._fail("サーバが終了しました: " + msg[:200])

    def _fail(self, msg: str):
        self._ready.stop()
        self._port = 0
        if self._proc is not None:
            self._proc = None
        self._set(self.ERROR, msg)

    def _check_ready(self):
        """ポートが開いたら準備完了（サーバはモデル読込後にbindする）。"""
        self._waited += 1
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            ok = s.connect_ex(("127.0.0.1", self._port)) == 0
        except Exception:
            ok = False
        finally:
            s.close()
        if ok:
            self._ready.stop()
            self._set(self.RUNNING, f"実行中 (port {self._port} / {self._device})")
        elif self._waited > 170:   # 約2分（初回のモデル読込/CUDA初期化を考慮）
            self.stop()
            self._set(self.ERROR, "起動がタイムアウトしました（初回はモデル読込で時間がかかります）")


_manager: ColorServerManager | None = None


def get_manager() -> ColorServerManager:
    """アプリ内で共有する単一のサーバ管理インスタンス。"""
    global _manager
    if _manager is None:
        _manager = ColorServerManager()
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_manager.stop)   # 終了時に子プロセスを確実に止める
    return _manager
