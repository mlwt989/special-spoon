@echo off
chcp 65001 >nul 2>&1
title Auto Video Editor - Web Server
cd /d "C:\Users\18095\WorkBuddy\2026-07-22-16-37-18\auto_video_editor\web_app"

set PYTHON_EXE=C:\Users\18095\.workbuddy\binaries\python\envs\default\Scripts\python.exe

echo ==================================================
echo   自动视频剪辑器 - 服务器已启动
echo   访问: http://localhost:5000
echo   关闭此窗口将停止服务器
echo ==================================================
echo.

:loop
"%PYTHON_EXE%" app.py
echo.
echo [%date% %time%] 服务器已停止，3秒后自动重启...
echo   (关闭此窗口可彻底停止)
timeout /t 3 /nobreak >nul
goto loop
