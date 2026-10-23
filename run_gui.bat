@echo off
chcp 65001 >nul
title Loca Web GUI (Coding Agent)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未在当前目录下找到虚拟环境 .venv\Scripts\python.exe
    echo 请先在终端运行: python -m venv .venv
    pause
    exit /b 1
)

echo ========================================================
echo   正在启动 Loca Web GUI (Coding Agent)...
echo   访问地址: http://127.0.0.1:8765
echo   服务就绪后会自动在默认浏览器中打开页面。
echo   关闭服务: 按 Ctrl + C 或直接关闭本窗口。
echo ========================================================
echo.

".venv\Scripts\python.exe" scripts\run_gui.py %*
