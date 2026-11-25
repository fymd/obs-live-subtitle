@echo off
chcp 65001 >nul
echo === OBS 实时字幕工具 - Windows 打包 ===

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 3.10+ 并勾选 Add to PATH
  pause
  exit /b 1
)

python -m pip install -U pip
python -m pip install -r requirements.txt pyinstaller

echo.
echo [1/2] 打包浏览器源版 subtitle_v2 ...
pyinstaller --noconfirm --onedir --console ^
  --name obs-live-subtitle ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all opencc ^
  --hidden-import translator ^
  subtitle_v2.py
if errorlevel 1 goto :fail

echo.
echo [2/2] 打包 WebSocket 版 subtitle_ws ...
pyinstaller --noconfirm --onedir --console ^
  --name obs-live-subtitle-ws ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all opencc ^
  --hidden-import translator ^
  --hidden-import obsws_python ^
  subtitle_ws.py
if errorlevel 1 goto :fail

echo.
echo 完成。产物目录：
echo   dist\obs-live-subtitle\
echo   dist\obs-live-subtitle-ws\
echo 请将整个文件夹打包分发，勿只拷贝单个 exe。
pause
exit /b 0

:fail
echo 打包失败，请查看上方报错。
pause
exit /b 1
