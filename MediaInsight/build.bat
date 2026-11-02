@echo off
rem 一键构建 MediaInsight.exe（Windows）。输出：dist\MediaInsight.exe
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :error
python tools\make_icon.py || goto :error
pyinstaller --noconfirm --clean MediaInsight.spec || goto :error
echo.
echo 构建完成：dist\MediaInsight.exe
goto :eof
:error
echo 构建失败，请查看上方错误信息。
exit /b 1
