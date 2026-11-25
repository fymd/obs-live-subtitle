"""
OBS 实时字幕工具 v2

功能：
- SSE 推送 + 临时/定稿字幕
- 可选繁转简
- 幻听词黑名单过滤
- initial_prompt 提升专有名词识别
- 网页设置面板（字号/颜色/位置），localStorage 持久化
- 云端翻译双语字幕（DeepL / OpenAI 兼容）
"""

import json
import queue
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from flask import Flask, Response

from translator import Translator

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

# 识别增强
ENABLE_T2S = True             # 繁体转简体（需要 opencc-python-reimplemented）
INITIAL_PROMPT = '以下是普通话直播内容。'  # 提示词，可加入游戏名、主播名等
BLOCK_WORDS = [               # 幻听词黑名单，命中则不显示
    '谢谢观看',
    '字幕由',
    '请不吝点赞',
    '订阅',
    '点赞',
    '打赏',
]

# 云端翻译（双语字幕）
ENABLE_TRANSLATE = True
TRANSLATE_PROVIDER = 'deepl'          # 'deepl' | 'openai'
TRANSLATE_API_KEY = ''                # 或环境变量 DEEPL_API_KEY / OPENAI_API_KEY
TRANSLATE_TARGET = 'EN'               # DeepL: EN / JA / KO ...
# OpenAI 兼容时可用：
OPENAI_BASE_URL = 'https://api.openai.com/v1'
OPENAI_MODEL = 'gpt-4o-mini'
TRANSLATE_ON_PARTIAL = False          # True=临时字幕也翻译（费额度）；False=仅定稿翻译
# ========================

# 可选：繁转简
_cc = None
if ENABLE_T2S:
    try:
        from opencc import OpenCC
        _cc = OpenCC('t2s')
    except ImportError:
        print('[警告] 未安装 opencc-python-reimplemented，跳过繁转简。可执行: pip install opencc-python-reimplemented')

translator = Translator(
    provider=TRANSLATE_PROVIDER,
    api_key=TRANSLATE_API_KEY,
    target_lang=TRANSLATE_TARGET,
    openai_base_url=OPENAI_BASE_URL,
    openai_model=OPENAI_MODEL,
) if ENABLE_TRANSLATE else None

model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

audio_q = queue.Queue()
subscribers = []
sub_lock = threading.Lock()


def clean(text: str) -> str:
    """过滤黑名单，可选繁转简。返回空字符串表示丢弃。"""
    if not text:
        return ''
    if any(b in text for b in BLOCK_WORDS):
        return ''
    if _cc is not None:
        text = _cc.convert(text)
    return text.strip()


def publish(kind, text):
    text = clean(text)
    if not text:
        return
    translation = ''
    if translator and translator.enabled:
        if kind == 'final' or TRANSLATE_ON_PARTIAL:
            translation = translator.translate(text)
    msg = json.dumps(
        {'type': kind, 'text': text, 'translation': translation},
        ensure_ascii=False,
    )
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
        initial_prompt=INITIAL_PROMPT or None,
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
            buf = buf[-SAMPLE_RATE:]
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

PAGE = r'''
<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body { margin: 0; background: transparent; overflow: hidden; font-family: 'Microsoft YaHei', sans-serif; }
  #wrap {
    position: fixed; left: 0; right: 0; bottom: var(--bottom, 40px);
    display: flex; justify-content: center; padding: 0 60px;
    pointer-events: none;
  }
  #sub {
    max-width: 1500px;
    overflow: hidden;
    display: flex; flex-direction: column; justify-content: flex-end; gap: 0.15em;
    text-align: center;
    line-height: var(--line-height, 1.3);
    word-break: break-all;
    font-weight: bold;
    transition: opacity 0.6s;
  }
  #sub .orig {
    font-size: var(--font-size, 46px);
    color: var(--color, #ffffff);
    text-shadow:
      var(--stroke, 2px) var(--stroke, 2px) calc(var(--stroke, 2px) * 2) var(--stroke-color, #000),
      calc(var(--stroke, 2px) * -1) calc(var(--stroke, 2px) * -1) calc(var(--stroke, 2px) * 2) var(--stroke-color, #000),
      var(--stroke, 2px) calc(var(--stroke, 2px) * -1) calc(var(--stroke, 2px) * 2) var(--stroke-color, #000),
      calc(var(--stroke, 2px) * -1) var(--stroke, 2px) calc(var(--stroke, 2px) * 2) var(--stroke-color, #000);
  }
  #sub .trans {
    font-size: calc(var(--font-size, 46px) * 0.72);
    color: var(--trans-color, #ffe08a);
    text-shadow:
      1px 1px 3px #000, -1px -1px 3px #000, 1px -1px 3px #000, -1px 1px 3px #000;
    opacity: 0.95;
  }
  #sub.partial { opacity: 0.85; }
  #sub.fade { opacity: 0; }

  #panel {
    position: fixed; top: 12px; right: 12px; z-index: 9999;
    background: rgba(0,0,0,0.75); color: #eee; padding: 12px 14px;
    border-radius: 8px; font-size: 13px; min-width: 220px;
    pointer-events: auto; display: none;
  }
  #panel.open { display: block; }
  #panel label { display: flex; justify-content: space-between; align-items: center; margin: 6px 0; gap: 8px; }
  #panel input[type="range"] { width: 120px; }
  #panel input[type="color"] { width: 36px; height: 24px; border: none; background: none; padding: 0; }
  #toggle {
    position: fixed; top: 12px; right: 12px; z-index: 10000;
    background: rgba(0,0,0,0.5); color: #fff; border: none;
    width: 32px; height: 32px; border-radius: 6px; cursor: pointer;
    font-size: 16px; pointer-events: auto;
  }
  #toggle:hover { background: rgba(0,0,0,0.75); }
</style></head>
<body>
<button id="toggle" title="字幕设置">⚙</button>
<div id="panel">
  <div style="font-weight:bold;margin-bottom:8px;">字幕样式</div>
  <label>字号 <input type="range" id="fontSize" min="24" max="96" value="46"></label>
  <label>文字色 <input type="color" id="color" value="#ffffff"></label>
  <label>描边色 <input type="color" id="strokeColor" value="#000000"></label>
  <label>描边粗 <input type="range" id="stroke" min="0" max="6" value="2"></label>
  <label>底边距 <input type="range" id="bottom" min="0" max="200" value="40"></label>
  <label>最大行数 <input type="range" id="maxLines" min="1" max="4" value="2"></label>
  <div style="margin-top:8px;opacity:0.7;font-size:11px;">设置保存在本机浏览器</div>
</div>
<div id="wrap"><div id="sub"><div class="orig"></div><div class="trans"></div></div></div>
<script>
  const el = document.getElementById('sub');
  const elOrig = el.querySelector('.orig');
  const elTrans = el.querySelector('.trans');
  const root = document.documentElement;
  const panel = document.getElementById('panel');
  const toggle = document.getElementById('toggle');
  let timer = null;

  const DEFAULTS = {
    fontSize: 46,
    color: '#ffffff',
    strokeColor: '#000000',
    stroke: 2,
    bottom: 40,
    maxLines: 2,
  };

  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem('obs-sub-settings') || '{}');
      return { ...DEFAULTS, ...s };
    } catch (e) {
      return { ...DEFAULTS };
    }
  }

  function apply(s) {
    root.style.setProperty('--font-size', s.fontSize + 'px');
    root.style.setProperty('--color', s.color);
    root.style.setProperty('--stroke-color', s.strokeColor);
    root.style.setProperty('--stroke', s.stroke + 'px');
    root.style.setProperty('--bottom', s.bottom + 'px');
    root.style.setProperty('--max-lines', s.maxLines);
    root.style.setProperty('--line-height', '1.3em');
  }

  function save(s) {
    localStorage.setItem('obs-sub-settings', JSON.stringify(s));
  }

  function bind() {
    const s = loadSettings();
    apply(s);
    document.getElementById('fontSize').value = s.fontSize;
    document.getElementById('color').value = s.color;
    document.getElementById('strokeColor').value = s.strokeColor;
    document.getElementById('stroke').value = s.stroke;
    document.getElementById('bottom').value = s.bottom;
    document.getElementById('maxLines').value = s.maxLines;

    function onChange() {
      const next = {
        fontSize: +document.getElementById('fontSize').value,
        color: document.getElementById('color').value,
        strokeColor: document.getElementById('strokeColor').value,
        stroke: +document.getElementById('stroke').value,
        bottom: +document.getElementById('bottom').value,
        maxLines: +document.getElementById('maxLines').value,
      };
      apply(next);
      save(next);
    }
    ['fontSize','color','strokeColor','stroke','bottom','maxLines'].forEach(id => {
      document.getElementById(id).addEventListener('input', onChange);
    });
  }

  toggle.addEventListener('click', () => panel.classList.toggle('open'));
  bind();

  function connect() {
    const es = new EventSource('/stream');
    es.onmessage = (e) => {
      const m = JSON.parse(e.data);
      clearTimeout(timer);
      elOrig.textContent = m.text || '';
      elTrans.textContent = m.translation || '';
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
                if q in subscribers:
                    subscribers.remove(q)

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    threading.Thread(target=recognize_loop, daemon=True).start()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32',
                        blocksize=int(SAMPLE_RATE * 0.1),
                        device=INPUT_DEVICE, callback=audio_callback):
        print('字幕页面已启动：http://127.0.0.1:%d' % PORT)
        print('提示：页面右上角 ⚙ 可调字号/颜色/位置（OBS 里也可临时打开）')
        app.run(host='127.0.0.1', port=PORT, threaded=True)
