# OBS 实时字幕工具

基于 faster-whisper 的本地实时中文字幕工具，通过浏览器源在 OBS 中叠加字幕，支持多平台同步推流。

## 功能特点

- 实时语音识别（中文）
- 本地运行，不上传音频
- 支持临时字幕 + 定稿字幕（v2）
- 繁体转简体、幻听词过滤、提示词增强
- 网页设置面板：字号 / 颜色 / 描边 / 位置（localStorage 持久化）
- 透明背景，带描边，适合直播
- CPU / GPU 均可运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 或手动：
# pip install faster-whisper sounddevice flask numpy opencc-python-reimplemented
```

### 2. 运行

```bash
# 最小可运行版本
python subtitle.py

# 推荐：升级版（SSE + 临时/定稿 + 样式设置）
python subtitle_v2.py
```

启动后访问：http://127.0.0.1:5000

页面右上角 **⚙** 可实时调整字号、颜色、描边、底边距、最大行数。

### 3. 在 OBS 中使用

1. 添加「浏览器」源
2. URL 填写 `http://127.0.0.1:5000`
3. 宽高建议 1920×200 或按需调整
4. 勾选「关闭时关闭源」「刷新浏览器时重新加载缓存」
5. 如需调样式，可临时在浏览器打开页面调整，设置会保存在本机

## 配置说明

主要参数在 `subtitle_v2.py` 顶部：

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| MODEL_SIZE | 模型大小 | CPU: small；GPU: large-v3-turbo |
| DEVICE | 运行设备 | cpu / cuda |
| COMPUTE_TYPE | 计算精度 | cpu: int8；cuda: float16 |
| STEP | 临时字幕刷新间隔（秒） | 1.0 |
| SILENCE_SEC | 静音多久定稿 | 0.7 |
| SILENCE_RMS | 静音音量阈值 | 按麦克风调整 |
| ENABLE_T2S | 是否繁转简 | True |
| INITIAL_PROMPT | 识别提示词（可加专有名词） | 见脚本 |
| BLOCK_WORDS | 幻听词黑名单 | 见脚本 |

详细调参与延迟分析见 [docs/development.md](docs/development.md)。

## 项目结构

```
obs-live-subtitle/
├── subtitle.py          # 第一版（轮询）
├── subtitle_v2.py       # 升级版（SSE + 临时/定稿 + 样式设置）
├── requirements.txt
├── README.md
├── LICENSE
└── docs/
    ├── development.md   # 详细开发文档
    └── prd-next.md      # 当前迭代需求
```

## 路线图

- [x] CPU 基础版本
- [x] v2：SSE + 临时/定稿字幕
- [x] 简繁转换、提示词、幻听词过滤
- [x] 网页设置页（字号、颜色、位置）
- [ ] 实时翻译 / 双语字幕
- [ ] obs-websocket 集成
- [ ] 原生 OBS 插件（长期）

## 注意事项

- 本工具仅在本地处理麦克风音频，不会上传语音。
- 请遵守各直播平台内容规范。
- 使用他人声音或有版权音乐时请自行确认授权。

## 许可

MIT License
