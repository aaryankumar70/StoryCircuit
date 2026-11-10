@echo off
echo ===================================================
echo CurioLoop - Unregistering Windows Task Scheduler
echo ===================================================

net session >nul 2>&1
if %errorLevel% == 0 (
    echo Administrative permissions confirmed.
) else (
    echo Requesting administrative privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

schtasks /delete /tn "CurioLoopScheduler" /f
python "%~dp0\manage_windows_task.py" unregister

echo [OK] CurioLoopScheduler task removed.
pause
