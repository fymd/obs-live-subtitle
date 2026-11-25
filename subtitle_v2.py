import json
import queue
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from flask import Flask, Response

# ===== 可以改的设置 =====
MODEL_SIZE = 'small'          # 有显卡后改 'large-v3-turbo'
DEVICE = 'cpu'                # 有显卡改 'cuda'
COMPUTE_TYPE = 'int8'         # 显卡用 'float16'
LANGUAGE = 'zh'
SAMPLE_RATE = 16000
STEP = 1.0                    # 说话过程中，每隔多少秒刷新一次临时字幕
SILENCE_SEC = 0.7             # 安静多久算一句话结束
SILENCE_RMS = 0.01            # 音量低于这个值算安静，按麦克风调
MAX_UTTERANCE = 12            # 一句话最长多少秒，超过强制定稿
INPUT_DEVICE = None           # 想指定设备就填编号，None 用系统默认
PORT = 5000
# ========================

model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

audio_q = queue.Queue()
subscribers = []
sub_lock = threading.Lock()


def publish(kind, text):
    msg = json.dumps({'type': kind, 'text': text}, ensure_ascii=False)
    with sub_lock:
        for q in subscribers:
            q.put(msg)


def audio_callback(indata, frames, time_info, status):
    audio_q.put(indata[:, 0].copy())


def rms(x):
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def transcribe(buf):
    segments, _ = model.transcribe(
        buf,
        language=LANGUAGE,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return ''.join(s.text for s in segments).strip()


def recognize_loop():
    buf = np.zeros(0, dtype=np.float32)
    has_speech = False
    last_run = 0.0
    sil_len = int(SAMPLE_RATE * SILENCE_SEC)
    while True:
        chunk = audio_q.get()
        if rms(chunk) > SILENCE_RMS:
            has_speech = True
        buf = np.concatenate([buf, chunk])

        if not has_speech:
            buf = buf[-SAMPLE_RATE:]   # 一直没人说话，只留 1 秒，防止堆积
            continue

        silent = len(buf) > sil_len and rms(buf[-sil_len:]) < SILENCE_RMS
        too_long = len(buf) > SAMPLE_RATE * MAX_UTTERANCE
        due = (time.time() - last_run) >= STEP

        if not (silent or too_long or due):
            continue
        last_run = time.time()

        text = transcribe(buf)
        if silent or too_long:
            if text:
                publish('final', text)
            buf = np.zeros(0, dtype=np.float32)
            has_speech = False
        elif text:
            publish('partial', text)


app = Flask(__name__)

PAGE = '''
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; background: transparent; overflow: hidden; }
  #wrap {
    position: fixed; left: 0; right: 0; bottom: 40px;
    display: flex; justify-content: center; padding: 0 60px;
  }
  #sub {
    max-width: 1500px; max-height: 2.6em; overflow: hidden;
    display: flex; flex-direction: column; justify-content: flex-end;
    text-align: center; line-height: 1.3; word-break: break-all;
    font: bold 46px 'Microsoft YaHei', sans-serif; color: white;
    text-shadow: 2px 2px 4px #000, -2px -2px 4px #000,
                 2px -2px 4px #000, -2px 2px 4px #000;
    transition: opacity 0.6s;
  }
  #sub.partial { opacity: 0.85; }
  #sub.fade { opacity: 0; }
</style></head>
<body><div id="wrap"><div id="sub"></div></div>
<script>
  const el = document.getElementById('sub');
  let timer = null;
  function connect() {
    const es = new EventSource('/stream');
    es.onmessage = (e) => {
      const m = JSON.parse(e.data);
      clearTimeout(timer);
      el.textContent = m.text;
      el.className = m.type === 'partial' ? 'partial' : '';
      if (m.type === 'final') {
        timer = setTimeout(() => { el.className = 'fade'; }, 3000);
      }
    };
    es.onerror = () => { es.close(); setTimeout(connect, 1000); };
  }
  connect();
</script></body></html>
'''


@app.route('/')
def index():
    return PAGE


@app.route('/stream')
def stream():
    q = queue.Queue()
    with sub_lock:
        subscribers.append(q)

    def gen():
        try:
            while True:
                try:
                    yield 'data: ' + q.get(timeout=15) + '\n\n'
                except queue.Empty:
                    yield ': keepalive\n\n'
        finally:
            with sub_lock:
                subscribers.remove(q)

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    threading.Thread(target=recognize_loop, daemon=True).start()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                        blocksize=int(SAMPLE_RATE * 0.1),
                        device=INPUT_DEVICE, callback=audio_callback):
        print('字幕页面已启动：http://127.0.0.1:%d' % PORT)
        app.run(host='127.0.0.1', port=PORT, threaded=True)
