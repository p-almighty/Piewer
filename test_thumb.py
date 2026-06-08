import sys, time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QThreadPool

app = QApplication(sys.argv)

# image_utils の _ThumbWorker/_ThumbSignals が動作するか確認
from image_utils import _ThumbWorker, _ThumbSignals
from config import PageSource

# テスト用に実際のZIP/フォルダを使わずダミーで信号発火確認
results = []

class FakeSource:
    def read(self, i):
        import io
        from PIL import Image
        img = Image.new("RGB", (100, 140), color=(i*30 % 255, 100, 150))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

source = FakeSource()
received = []

def on_done(idx, raw, w, h):
    received.append((idx, len(raw), w, h))
    print(f"[OK] on_done called: idx={idx}, raw_len={len(raw)}, w={w}, h={h}")

# 3つワーカーを起動
pool = QThreadPool.globalInstance()
workers = {}
for i in range(3):
    worker = _ThumbWorker(source, i)
    worker.signals.done.connect(on_done)
    workers[i] = worker
    pool.start(worker)

def check():
    print(f"After 2s: received {len(received)} results: {received}")
    if len(received) == 0:
        print("FAIL: No signals received!")
    else:
        print("PASS: Signals received correctly")
    app.quit()

QTimer.singleShot(2000, check)
sys.exit(app.exec())
