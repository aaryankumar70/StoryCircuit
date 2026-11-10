@echo off
echo ===================================================
echo CurioLoop - Registering Windows Task Scheduler
echo ===================================================

:: Check for Administrative Rights and elevate if needed
net session >nul 2>&1
if %errorLevel% == 0 (
    echo Administrative permissions confirmed.
) else (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0\.."
schtasks /create /xml "%~dp0\..\data\CurioLoopScheduler.xml" /tn "CurioLoopScheduler" /f

echo.
if %errorLevel% == 0 (
    echo [OK] CurioLoopScheduler successfully registered in Windows Task Scheduler!
) else (
    echo [ERROR] Failed to register task with error code: %errorLevel%
)

echo.
pause
