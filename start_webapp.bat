@echo off
title Auto Video Editor - Web Server
cd /d "C:\Users\18095\WorkBuddy\2026-07-22-16-37-18\auto_video_editor\web_app"

set PYTHON_EXE=C:\Users\18095\.workbuddy\binaries\python\envs\default\Scripts\python.exe

echo ==================================================
echo   Auto Video Editor - Server Started
echo   Open: http://localhost:5000
echo   Close this window to stop the server
echo ==================================================
echo.

:loop
"%PYTHON_EXE%" app.py
echo.
echo [%date% %time%] Server stopped, restarting in 3s...
echo   (Close this window to stop completely)
timeout /t 3 /nobreak >nul
goto loop
