@echo off
setlocal
title Job MCP - Starting
cd /d "%~dp0"

set "PYTHON="
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
if not defined PYTHON (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo Python 3 nahi mila. Python install karo ya project ka .venv setup karo.
    pause
    exit /b 1
)

if not exist "web\dist\index.html" (
    echo Frontend build nahi mila: web\dist\index.html
    echo Build karne ke liye web folder mein npm install aur npm run build chalao.
    pause
    exit /b 1
)

echo Job MCP start ho raha hai: http://127.0.0.1:8765
echo Browser nahi khule toh is address ko browser mein kholo: http://127.0.0.1:8765
echo App band karne ke liye is window mein Ctrl+C dabao.
%PYTHON% app.py
set "APP_EXIT=%ERRORLEVEL%"
echo.
if not "%APP_EXIT%"=="0" echo App error ke saath band hua (exit code %APP_EXIT%). Upar error dekho.
echo Server band ho gaya.
pause
endlocal
