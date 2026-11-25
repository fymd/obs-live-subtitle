# OBS 实时字幕工具

基于 faster-whisper 的本地实时中文字幕工具。支持浏览器源与 obs-websocket 两种显示方式，并支持云端 API 双语字幕。

## 功能特点

- 实时语音识别（中文，本地 Whisper）
- 本地运行识别，不上传音频
- 临时字幕 + 定稿字幕
- 繁体转简体、幻听词过滤、提示词增强
- **云端翻译双语字幕**（DeepL / OpenAI 兼容）
- 浏览器版：网页设置面板 + 原文/译文双行
- WebSocket 版：直接更新 OBS 文本源（可双源）
- CPU / GPU 均可运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置翻译（可选）

在脚本顶部，或使用环境变量：

```bash
# DeepL（推荐，免费额度约 50 万字符/月）
export DEEPL_API_KEY='你的DeepL密钥'   # Free 版密钥以 :fx 结尾

# 或 OpenAI 兼容
export OPENAI_API_KEY='sk-...'
```

脚本内也可直接写：

```python
ENABLE_TRANSLATE = True
TRANSLATE_PROVIDER = 'deepl'   # 或 'openai'
TRANSLATE_API_KEY = ''         # 留空则读环境变量
TRANSLATE_TARGET = 'EN'        # EN / JA / KO ...
```

### 3. 运行

#### 方式 A：浏览器源

```bash
python subtitle_v2.py
```

- 访问 http://127.0.0.1:5000
- OBS 添加浏览器源，URL 填上述地址
- 原文白字 + 译文黄字双行显示

#### 方式 B：obs-websocket

1. OBS：工具 → WebSocket 服务器设置 → 启用并设密码
2. 添加文本源，命名为 `字幕`；双语时可再加 `字幕翻译`
3. 配置 `subtitle_ws.py` 中的 `OBS_PASSWORD`、`TEXT_SOURCE_NAME` 等
4. 运行：

```bash
python subtitle_ws.py
```

## 配置说明

| 参数 | 说明 |
|------|------|
| MODEL_SIZE / DEVICE | Whisper 模型与设备 |
| ENABLE_TRANSLATE | 是否开启云端翻译 |
| TRANSLATE_PROVIDER | `deepl` 或 `openai` |
| TRANSLATE_API_KEY | API 密钥（优先环境变量） |
| TRANSLATE_TARGET | 目标语言，如 EN、JA、KO |
| TRANSLATE_ON_PARTIAL | 临时字幕是否也翻译（费额度） |
| TEXT_SOURCE_NAME | OBS 中文文本源名称 |
| TRANSLATION_SOURCE_NAME | OBS 译文文本源（空则合并到一行） |

## 打包成 exe

Windows 用户可直接运行仓库中的 `build_windows.bat`，或阅读 [build_exe.md](build_exe.md)。

```bat
build_windows.bat
```

产物在 `dist\\obs-live-subtitle\\` 与 `dist\\obs-live-subtitle-ws\\`，请分发**整个文件夹**。模型首次运行自动下载，不打进包。

## 项目结构

```
obs-live-subtitle/
├── subtitle.py          # 第一版（轮询）
├── subtitle_v2.py       # 浏览器源版 + 双语
├── subtitle_ws.py       # WebSocket 版 + 双语
├── translator.py        # 云端翻译模块
├── build_windows.bat    # Windows 一键打包
├── build_exe.md         # 打包说明
├── requirements.txt
├── README.md
└── docs/
```

## 路线图

- [x] CPU / GPU 识别
- [x] SSE 临时/定稿字幕
- [x] 简繁、提示词、幻听过滤
- [x] 网页样式设置
- [x] obs-websocket 集成
- [x] 云端翻译双语字幕
- [x] 打包说明与脚本
- [ ] 原生 OBS 插件（长期）

## 注意事项

- 识别在本地完成；仅翻译文本会发往云端 API。
- 请遵守各直播平台内容规范与 API 服务条款。
- API Key 请勿提交到公开仓库，建议用环境变量。

## 许可

MIT License
