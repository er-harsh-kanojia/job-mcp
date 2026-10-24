@echo off
setlocal
title Job MCP - Automated Setup
cd /d "%~dp0"

echo ============================================================
echo               Job MCP Setup Launcher
echo ============================================================
echo.

where powershell >nul 2>nul
if %ERRORLEVEL% equ 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    set "SETUP_EXIT=%ERRORLEVEL%"
) else (
    echo PowerShell nahi mila. Setup script PowerShell par run hoti hai.
    pause
    exit /b 1
)

echo.
if not "%SETUP_EXIT%"=="0" (
    echo Setup error ke saath band hua (code %SETUP_EXIT%). Upar error messages dekhein.
) else (
    echo Setup successfully complete ho gaya!
    echo App start karne ke liye 'start.bat' chalao.
)

pause
endlocal
