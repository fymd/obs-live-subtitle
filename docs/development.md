# OBS 实时字幕工具：详细开发文档

适用对象：已经拿到第一版 subtitle.py，想理解它怎么工作、怎么改、怎么继续做成更完整的工具的开发者。

## 1. 总体架构

整个工具分成四层，数据单向流动：

1. 音频采集层：sounddevice 从麦克风（或立体声混音）持续读取 16kHz 单声道音频，放进队列。
2. 识别层：后台线程从队列取音频，攒成一段缓冲，交给 faster-whisper 转成文字。
3. 服务层：Flask 起一个本地 HTTP 服务，对外提供字幕页面和字幕数据。
4. 显示层：OBS 的浏览器源加载本地页面，页面把文字画成带描边的字幕，背景透明。

数据流：麦克风 → 音频队列 → 识别线程 → 当前字幕文本 → Flask → 字幕网页 → OBS 画面 → 推流到抖音、B站、小红书。

这样设计的好处：字幕是画进画面里的，所以多平台同步推流时每个平台自动都带字幕，不需要分别适配。

## 2. 第一版脚本逐段讲解

### 2.1 配置区

- MODEL_SIZE：模型大小。tiny、base、small 适合 CPU；medium、large-v3-turbo 适合独立显卡。
- LANGUAGE：固定为 zh 比自动检测更快更准。
- CHUNK_SECONDS：每隔多少秒触发一次识别。
- PORT：本地网页端口。

### 2.2 模型加载

WhisperModel 在启动时加载一次，之后复用。GPU 用 device=cuda 加 compute_type=float16；CPU 用 device=cpu 加 compute_type=int8。int8 是量化，速度快、内存小，准确率略降。

### 2.3 音频回调

audio_callback 由 sounddevice 在独立线程里调用，只做一件事：把这一小块音频复制进队列。回调里不能做耗时操作，否则会丢音频。

### 2.4 识别循环

recognize_loop 不断从队列取音频拼成缓冲，缓冲够长就识别一次。关键细节：

- 缓冲最多只保留最近 6 秒，防止越积越长导致越来越慢。
- 识别完后只留 1 秒尾巴，用来衔接下一段，避免一句话被从中间切断。
- vad_filter=True 会先用语音活动检测去掉静音，减少静音时的幻听。
- beam_size=1 是贪心解码，速度最快。
- condition_on_previous_text=False 避免模型被上一段文字带偏、陷入重复。

### 2.5 服务与页面

页面每 300 毫秒向 /text 拉一次最新文字并显示。这是轮询方式，最简单，缺点是有最多 300 毫秒的额外延迟，也不能区分「还没说完」和「说完了」。第 4 节的升级版改成服务器推送。

## 3. 延迟从哪里来

字幕出现的总延迟大致等于下面几项相加：

- 采集块长度：约 0.1 秒。
- 触发间隔：CHUNK_SECONDS，第一版是 2 秒，这是最大头。
- 模型推理：GPU 上 large-v3-turbo 处理几秒音频通常零点几秒；CPU 的 small 可能一到两秒。
- 页面刷新：轮询 0.3 秒，改成推送后接近 0。
- OBS 渲染：一帧左右，可忽略。

优化顺序建议：先把触发间隔降到 1 秒（升级版做法），再确认确实在用 GPU，最后才考虑换更小的模型。

## 4. 升级版脚本（v2）

v2 解决三个问题：

1. 用服务器推送（SSE）代替轮询，延迟更低。
2. 区分「临时字幕」和「定稿字幕」：说话过程中滚动刷新，停顿后定稿并在几秒后淡出。
3. 长句自动换行，只显示最后两行。

用简单的音量判断「说话是否停顿」，不额外依赖。把下面保存为 subtitle_v2.py：

```python
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
```

### 4.1 v2 的行为

- 你开口说话后，每秒刷新一次「临时字幕」，略微变淡，表示还在识别中。
- 停顿约 0.7 秒后，这一句定稿，变成正常亮度，3 秒后淡出。
- 单句超过 12 秒会强制定稿，避免缓冲无限变长。
- 页面最多显示两行，超出的旧内容自动被挤出去。

### 4.2 调参指南

- 字幕老是被中途切断：把 SILENCE_SEC 调大，比如 1.0。
- 说话停顿后字幕定稿太慢：把 SILENCE_SEC 调小，比如 0.5。
- 房间有底噪，一直触发识别：把 SILENCE_RMS 调大，比如 0.02。
- 声音小被当成安静：把 SILENCE_RMS 调小，比如 0.005，或者调大麦克风增益。
- 想要更快的临时字幕：STEP 调到 0.7，但显卡压力会变大。

## 5. 常用增强功能

### 5.1 简繁转换

Whisper 输出中文有时是繁体。安装 `pip install opencc-python-reimplemented`，然后在 transcribe 返回前转换：

```python
from opencc import OpenCC
cc = OpenCC('t2s')
# transcribe 函数最后一行改成：
return cc.convert(''.join(s.text for s in segments).strip())
```

### 5.2 提示词与专有名词

transcribe 支持 initial_prompt 参数，把你直播里常出现的人名、游戏名、品牌名写进去，能明显减少识别错误。例如 initial_prompt='以下是普通话直播内容，常见词：某某游戏、某某主播'。较新版本的 faster-whisper 还支持 hotwords 参数，可查看你安装版本的文档确认。

### 5.3 选择音频设备

命令行运行 `python -m sounddevice` 会列出所有设备和编号。把想用的编号填进 INPUT_DEVICE。想给电脑里播放的声音加字幕，需要先在 Windows 录制设备里启用立体声混音，再选它。

### 5.4 屏蔽幻听词

Whisper 在静音或噪声里偶尔会输出固定的怪句子，比如「谢谢观看」「字幕由某某提供」。可以在 publish 之前加一个黑名单过滤：

```python
BLOCK = ['谢谢观看', '字幕由', '请不吝点赞']
def clean(text):
    return '' if any(b in text for b in BLOCK) else text
```

### 5.5 实时翻译

在 transcribe 得到中文后，再调用翻译。两条路线：本地的开源翻译模型（离线，对显存有额外要求），或者云端翻译接口（质量好，需要密钥和网络）。建议翻译结果作为第二行单独推送，页面里用另一个样式显示，不要和原文混在一起。

## 6. 字幕与画面音频不同步怎么办

字幕天然比声音晚一两秒出现。两种处理方式：

- 接受它：观众看直播本来就有延迟，一般一两秒的字幕滞后能接受。
- 对齐它：在 OBS 里给画面和音频同时加延迟。视频源加「渲染延迟」滤镜，音频在「高级音频属性」里设置「同步偏移」，两者设成相同的毫秒数。代价是你自己预览和直播之间的互动也会同步变慢。

## 7. 做成真正的 OBS 插件的三条路线

| 路线 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| A 浏览器源（现在） | Python 程序加本地网页 | 开发最快，跨平台，易调试 | 需要单独运行一个程序 |
| B obs-websocket | Python 通过 obs-websocket 直接更新 OBS 里的文本源 | 不用浏览器源，样式用 OBS 自带文本源调 | 样式能力不如网页，要配置 WebSocket 密码 |
| C 原生 C++ 插件 | 用官方 obs-plugintemplate，写音频滤镜，内嵌 whisper.cpp | 体验最好，一个插件搞定 | 开发门槛高，要处理跨平台构建和发布 |

建议顺序：先把路线 A 用顺，确认功能和参数；需要更方便的使用体验时再考虑 B；确实要发布给很多人用时才做 C。做 C 之前，先去看看已有的开源项目，比如 obs-localvocal，了解别人怎么做的，也评估是否直接贡献代码更划算，具体情况请以其仓库当前状态为准。

路线 B 的要点：OBS 28 及以上版本内置 obs-websocket，在「工具」菜单里启用并设置密码。Python 端可以用 obsws-python 库，调用 SetInputSettings 更新文本源的 text 字段。

## 8. 测试与调试清单

### 8.1 分步验证

第一步，不用麦克风，先拿一段录音确认模型本身能跑：

```python
from faster_whisper import WhisperModel
m = WhisperModel('small', device='cpu', compute_type='int8')
segs, info = m.transcribe('test.wav', language='zh')
for s in segs:
    print(round(s.start, 1), round(s.end, 1), s.text)
```

第二步，确认麦克风有信号：用 `python -m sounddevice` 找到设备，再写几行打印音量的小脚本，对着麦克风说话看数值是否变化。

第三步，跑完整脚本，用浏览器直接打开 http://127.0.0.1:5000，看字幕是否出现，再去 OBS 里加浏览器源。

### 8.2 报错速查

- 找不到 cudnn 或 cublas 的动态库：说明 CUDA 12 或 cuDNN 9 没装好或路径没加入系统环境变量，先用 CPU 模式。
- PortAudio 或 sounddevice 打不开设备：设备被别的软件独占，或者选错了设备编号。
- 页面打开了但没有字幕：先看终端有没有输出，再检查 SILENCE_RMS 是否太大，导致一直被当成安静。
- 浏览器源里字幕是黑底：删掉 OBS 浏览器源自定义 CSS 里的背景色那一行。
- 字幕只显示一次后不动了：检查是不是电脑休眠或者麦克风被切换，重启脚本即可。

## 9. 打包成 exe 分发

想让不会 Python 的人也能用，可以用 PyInstaller：

```
pip install pyinstaller
pyinstaller --onedir --collect-all faster_whisper --collect-all ctranslate2 subtitle_v2.py
```

注意：

- 建议用 onedir 而不是 onefile，启动更快，也更不容易漏掉动态库。
- 模型文件很大，不建议打进 exe，而是第一次运行时下载，或者让用户把模型放到指定文件夹，用 WhisperModel 的本地路径参数加载。
- 带 GPU 支持的包体积会非常大，可以分别提供 CPU 版和 GPU 版。
- 打包后务必在一台干净的电脑上测试，很多问题只有在没装开发环境的机器上才暴露。

## 10. 仓库结构建议

```
obs-live-subtitle/
  subtitle.py          第一版，最小可运行
  subtitle_v2.py       升级版
  requirements.txt
  README.md
  LICENSE
  docs/
    development.md     把本文档放这里
```

提交信息建议用简短的动词开头，比如「add v2 with SSE streaming」，方便以后回看历史。

## 11. 路线图

按价值和难度排序：

1. 跑通 CPU 版，再切换到 GPU，记录实际延迟。
2. 升级到 v2，调好 SILENCE_RMS 和 SILENCE_SEC。
3. 加简繁转换、提示词、幻听词过滤。
4. 加一个简单的设置页面，在网页里调字号、颜色、位置，不用改代码。
5. 加实时翻译，做双语字幕。
6. 视需要走 obs-websocket 或原生插件路线。
7. 打包发布。

## 12. 使用提醒

各直播平台对内容和第三方推流有各自的规范，字幕里如果出现违规词，同样会被平台处理。直播中使用他人声音或有版权的音乐，请自行确认授权。本工具只在本地处理你自己的麦克风音频，不会上传语音。
