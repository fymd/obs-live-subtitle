"""
OBS 实时字幕工具 — WebSocket 版

通过 obs-websocket 直接更新 OBS 文本源，无需浏览器源。

前置条件：
1. OBS 28+，工具 → WebSocket 服务器设置 → 启用，并设置密码
2. 在当前场景添加一个「文本 (GDI+)」或「文本 (FreeType 2)」源，记住源名称
3. pip install obsws-python

用法：
  python subtitle_ws.py
"""

import queue
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

try:
    import obsws_python as obs
except ImportError:
    raise SystemExit(
        '请先安装: pip install obsws-python\n'
        '并确认 OBS 已启用 WebSocket 服务器（工具 → WebSocket 服务器设置）'
    )

# ===== 可以改的设置 =====
MODEL_SIZE = 'small'
DEVICE = 'cpu'
COMPUTE_TYPE = 'int8'
LANGUAGE = 'zh'
SAMPLE_RATE = 16000
STEP = 1.0
SILENCE_SEC = 0.7
SILENCE_RMS = 0.01
MAX_UTTERANCE = 12
INPUT_DEVICE = None

# 识别增强
ENABLE_T2S = True
INITIAL_PROMPT = '以下是普通话直播内容。'
BLOCK_WORDS = [
    '谢谢观看',
    '字幕由',
    '请不吝点赞',
    '订阅',
    '点赞',
    '打赏',
]

# 云端翻译（双语）
ENABLE_TRANSLATE = True
TRANSLATE_PROVIDER = 'deepl'          # 'deepl' | 'openai'
TRANSLATE_API_KEY = ''                # 或环境变量 DEEPL_API_KEY / OPENAI_API_KEY
TRANSLATE_TARGET = 'EN'
OPENAI_BASE_URL = 'https://api.openai.com/v1'
OPENAI_MODEL = 'gpt-4o-mini'
TRANSLATE_ON_PARTIAL = False

# OBS WebSocket
OBS_HOST = 'localhost'
OBS_PORT = 4455
OBS_PASSWORD = ''                 # 在 OBS「工具 → WebSocket 服务器设置」里设置的密码
TEXT_SOURCE_NAME = '字幕'         # 中文文本源名称
TRANSLATION_SOURCE_NAME = '字幕翻译'  # 译文文本源，留空则合并到中文源（原文\\n译文）
CLEAR_AFTER_SEC = 3.0             # 定稿后多少秒清空文本（0 = 不自动清空）
# ========================

from translator import Translator

_cc = None
if ENABLE_T2S:
    try:
        from opencc import OpenCC
        _cc = OpenCC('t2s')
    except ImportError:
        print('[警告] 未安装 opencc-python-reimplemented，跳过繁转简')

translator = Translator(
    provider=TRANSLATE_PROVIDER,
    api_key=TRANSLATE_API_KEY,
    target_lang=TRANSLATE_TARGET,
    openai_base_url=OPENAI_BASE_URL,
    openai_model=OPENAI_MODEL,
) if ENABLE_TRANSLATE else None

model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
audio_q = queue.Queue()
ws_client = None
_clear_timer = None
_timer_lock = threading.Lock()


def clean(text: str) -> str:
    if not text:
        return ''
    if any(b in text for b in BLOCK_WORDS):
        return ''
    if _cc is not None:
        text = _cc.convert(text)
    return text.strip()


def set_obs_text(text: str, translation: str = ''):
    """更新 OBS 文本源内容。"""
    global ws_client
    if ws_client is None:
        return
    try:
        if TRANSLATION_SOURCE_NAME:
            ws_client.set_input_settings(
                name=TEXT_SOURCE_NAME,
                settings={'text': text},
                overlay=True,
            )
            ws_client.set_input_settings(
                name=TRANSLATION_SOURCE_NAME,
                settings={'text': translation},
                overlay=True,
            )
        else:
            combined = text
            if translation:
                combined = f'{text}\n{translation}'
            ws_client.set_input_settings(
                name=TEXT_SOURCE_NAME,
                settings={'text': combined},
                overlay=True,
            )
    except Exception as e:
        print(f'[OBS] 更新文本失败: {e}')


def schedule_clear():
    """定稿后延迟清空。"""
    global _clear_timer

    def _clear():
        time.sleep(CLEAR_AFTER_SEC)
        set_obs_text('', '')

    with _timer_lock:
        if _clear_timer is not None and _clear_timer.is_alive():
            pass
        if CLEAR_AFTER_SEC > 0:
            _clear_timer = threading.Thread(target=_clear, daemon=True)
            _clear_timer.start()


def cancel_clear():
    """有新字幕时取消清空意图（用时间戳更稳，这里简化为不取消旧线程）。"""
    pass


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

        text = clean(transcribe(buf))
        if silent or too_long:
            if text:
                translation = ''
                if translator and translator.enabled:
                    translation = translator.translate(text)
                set_obs_text(text, translation)
                schedule_clear()
            buf = np.zeros(0, dtype=np.float32)
            has_speech = False
        elif text:
            translation = ''
            if translator and translator.enabled and TRANSLATE_ON_PARTIAL:
                translation = translator.translate(text)
            set_obs_text(text, translation)


def connect_obs():
    global ws_client
    print(f'正在连接 OBS WebSocket {OBS_HOST}:{OBS_PORT} ...')
    try:
        ws_client = obs.ReqClient(
            host=OBS_HOST,
            port=OBS_PORT,
            password=OBS_PASSWORD or '',
            timeout=5,
        )
        try:
            resp = ws_client.get_input_settings(TEXT_SOURCE_NAME)
            print(f'已连接，文本源「{TEXT_SOURCE_NAME}」就绪')
            return True
        except Exception:
            print(f'[警告] 找不到名为「{TEXT_SOURCE_NAME}」的输入源。')
            print('请在 OBS 当前场景添加文本源，并把 TEXT_SOURCE_NAME 改成完全一致的名称。')
            return True
    except Exception as e:
        print(f'连接 OBS 失败: {e}')
        print('请检查：')
        print('  1. OBS 已启动')
        print('  2. 工具 → WebSocket 服务器设置 → 已启用')
        print('  3. 端口与密码与脚本中 OBS_PORT / OBS_PASSWORD 一致')
        return False


if __name__ == '__main__':
    if not connect_obs():
        raise SystemExit(1)

    threading.Thread(target=recognize_loop, daemon=True).start()
    print(f'识别已启动，将更新 OBS 文本源「{TEXT_SOURCE_NAME}」')
    print('按 Ctrl+C 退出')

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32',
            blocksize=int(SAMPLE_RATE * 0.1),
            device=INPUT_DEVICE,
            callback=audio_callback,
        ):
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print('\n已退出')
        try:
            set_obs_text('', '')
        except Exception:
            pass
