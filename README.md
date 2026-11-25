# OBS 实时字幕工具

基于 faster-whisper 的本地实时中文字幕工具。支持两种显示方式：

1. **浏览器源**（`subtitle_v2.py`）— 网页字幕，样式可调，跨平台
2. **obs-websocket**（`subtitle_ws.py`）— 直接改 OBS 文本源，无需浏览器源

## 功能特点

- 实时语音识别（中文）
- 本地运行，不上传音频
- 临时字幕 + 定稿字幕
- 繁体转简体、幻听词过滤、提示词增强
- 浏览器版：网页设置面板（字号/颜色/描边/位置）
- WebSocket 版：直接更新 OBS 文本源
- CPU / GPU 均可运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 选择运行方式

#### 方式 A：浏览器源（推荐入门）

```bash
python subtitle_v2.py
```

- 访问 http://127.0.0.1:5000
- OBS 添加「浏览器」源，URL 填上述地址
- 页面右上角 ⚙ 可调样式

#### 方式 B：obs-websocket 直接改文本源

1. OBS 28+：工具 → **WebSocket 服务器设置** → 启用，设置密码
2. 在场景中添加「文本 (GDI+)」或「文本 (FreeType 2)」源，命名为例如 `字幕`
3. 编辑 `subtitle_ws.py` 顶部：

```python
OBS_PASSWORD = '你的密码'
TEXT_SOURCE_NAME = '字幕'   # 必须与 OBS 源名称完全一致
```

4. 运行：

```bash
python subtitle_ws.py
```

说话后，OBS 里该文本源会实时更新；停顿定稿后约 3 秒自动清空。

## 配置说明

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| MODEL_SIZE | 模型大小 | CPU: small；GPU: large-v3-turbo |
| DEVICE | 运行设备 | cpu / cuda |
| COMPUTE_TYPE | 计算精度 | cpu: int8；cuda: float16 |
| STEP | 临时字幕刷新间隔（秒） | 1.0 |
| SILENCE_SEC | 静音多久定稿 | 0.7 |
| SILENCE_RMS | 静音音量阈值 | 按麦克风调整 |
| ENABLE_T2S | 是否繁转简 | True |
| INITIAL_PROMPT | 识别提示词 | 可加游戏名、主播名 |
| BLOCK_WORDS | 幻听词黑名单 | 见脚本 |
| OBS_HOST / PORT / PASSWORD | WebSocket 连接 | 默认 localhost:4455 |
| TEXT_SOURCE_NAME | OBS 文本源名称 | 与 OBS 完全一致 |
| CLEAR_AFTER_SEC | 定稿后清空延迟 | 3.0（0=不清空） |

详细开发说明见 [docs/development.md](docs/development.md)。

## 项目结构

```
obs-live-subtitle/
├── subtitle.py          # 第一版（轮询浏览器）
├── subtitle_v2.py       # 浏览器源版（SSE + 样式设置）
├── subtitle_ws.py       # WebSocket 版（直接改文本源）
├── requirements.txt
├── README.md
├── LICENSE
└── docs/
    ├── development.md
    └── prd-next.md
```

## 路线图

- [x] CPU 基础版本
- [x] v2：SSE + 临时/定稿字幕
- [x] 简繁转换、提示词、幻听词过滤
- [x] 网页设置页（字号、颜色、位置）
- [x] obs-websocket 集成
- [ ] 实时翻译 / 双语字幕
- [ ] 原生 OBS 插件（长期）

## 注意事项

- 本工具仅在本地处理麦克风音频，不会上传语音。
- 请遵守各直播平台内容规范。
- 使用他人声音或有版权音乐时请自行确认授权。

## 许可

MIT License
