# 打包成 exe 说明

目标：让不会 Python 的用户也能运行字幕工具。

## 推荐方式（Windows）

在 **Windows** 上打包（OBS 用户多为 Windows），不要在 Linux 交叉编译。

### 1. 环境

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

### 2. 打包浏览器源版（subtitle_v2）

```bat
pyinstaller --noconfirm --onedir --console ^
  --name obs-live-subtitle ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all opencc ^
  --hidden-import translator ^
  subtitle_v2.py
```

### 3. 打包 WebSocket 版（subtitle_ws）

```bat
pyinstaller --noconfirm --onedir --console ^
  --name obs-live-subtitle-ws ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all opencc ^
  --hidden-import translator ^
  --hidden-import obsws_python ^
  subtitle_ws.py
```

### 4. 产物

- 输出目录：`dist\obs-live-subtitle\` 或 `dist\obs-live-subtitle-ws\`
- 双击其中的 `.exe` 启动
- **不要**用 `--onefile`：启动更慢，且易漏动态库

### 5. 模型

Whisper 模型首次运行会自动下载到用户目录（如 `%USERPROFILE%\.cache\huggingface`），体积较大，**不要**打进包。

可在脚本里改为本地路径：

```python
model = WhisperModel('/path/to/model', device=DEVICE, compute_type=COMPUTE_TYPE)
```

### 6. 分发清单

把整个 `dist\obs-live-subtitle\` 文件夹打成 zip，附带：

- 简短使用说明（如何设 OBS、如何填 API Key）
- 说明需允许防火墙访问本地端口（浏览器版 5000）
- CPU 版 / GPU 版可分开打（GPU 需 CUDA 环境）

### 7. 干净机器测试

在未装 Python 的电脑上解压运行，确认：

1. 能启动、能出字
2. 麦克风权限正常
3. 浏览器源 / WebSocket 均可用

## Linux / macOS

同样可用 `pyinstaller --onedir ...`，产物为对应平台可执行文件，不能在 Windows 上直接跑。

## 一键脚本

见仓库内 `build_windows.bat`（在 Windows 下双击或命令行运行）。
