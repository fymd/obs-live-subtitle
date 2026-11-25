"""
OBS 实时字幕工具 - 第一版（最小可运行）

使用轮询方式获取字幕。推荐使用 subtitle_v2.py（SSE + 临时/定稿字幕）。
详细说明见 docs/development.md
"""

import queue
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from flask import Flask, jsonify

# ===== 可以改的设置 =====
MODEL_SIZE = 'small'          # tiny / base / small（CPU）; medium / large-v3-turbo（GPU）
DEVICE = 'cpu'                # 'cpu' 或 'cuda'
COMPUTE_TYPE = 'int8'         # cpu: int8; cuda: float16
LANGUAGE = 'zh'
SAMPLE_RATE = 16000
CHUNK_SECONDS = 2.0           # 每隔多少秒识别一次
PORT = 5000
INPUT_DEVICE = None
# ========================

model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
audio_q = queue.Queue()
current_text = ''
text_lock = threading.Lock()


def audio_callback(indata, frames, time_info, status):
    audio_q.put(indata[:, 0].copy())


def recognize_loop():
    global current_text
    buf = np.zeros(0, dtype=np.float32)
    while True:
        chunk = audio_q.get()
        buf = np.concatenate([buf, chunk])
        # 最多保留最近 6 秒
        max_len = int(SAMPLE_RATE * 6)
        if len(buf) > max_len:
            buf = buf[-max_len:]
        if len(buf) < int(SAMPLE_RATE * CHUNK_SECONDS):
            continue
        segments, _ = model.transcribe(
            buf,
            language=LANGUAGE,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
        )
        text = ''.join(s.text for s in segments).strip()
        if text:
            with text_lock:
                current_text = text
        # 留 1 秒尾巴衔接下一段
        buf = buf[-SAMPLE_RATE:]


app = Flask(__name__)

PAGE = '''
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; background: transparent; overflow: hidden; }
  #sub {
    position: fixed; left: 0; right: 0; bottom: 40px;
    text-align: center; padding: 0 60px;
    font: bold 46px 'Microsoft YaHei', sans-serif; color: white;
    text-shadow: 2px 2px 4px #000, -2px -2px 4px #000,
                 2px -2px 4px #000, -2px 2px 4px #000;
  }
</style></head>
<body><div id="sub"></div>
<script>
  const el = document.getElementById('sub');
  setInterval(async () => {
    try {
      const r = await fetch('/text');
      const j = await r.json();
      el.textContent = j.text || '';
    } catch (e) {}
  }, 300);
</script></body></html>
'''


@app.route('/')
def index():
    return PAGE


@app.route('/text')
def text():
    with text_lock:
        return jsonify({'text': current_text})


if __name__ == '__main__':
    threading.Thread(target=recognize_loop, daemon=True).start()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                        blocksize=int(SAMPLE_RATE * 0.1),
                        device=INPUT_DEVICE, callback=audio_callback):
        print(f'字幕页面已启动：http://127.0.0.1:{PORT}')
        app.run(host='127.0.0.1', port=PORT, threaded=True)
