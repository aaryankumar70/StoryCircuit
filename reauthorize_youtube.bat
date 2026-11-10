@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ================================================================
echo CurioLoop YouTube OAuth Reauthorization Helper
echo ================================================================
echo Launching browser authorization with full upload and scheduling scopes...
echo.

python scripts\auth_youtube.py --force --scope-mode full --yes
if errorlevel 1 (
    echo.
    echo [ERROR] YouTube OAuth reauthorization failed or was cancelled.
    pause
    exit /b 1
)

echo.
echo Validating updated credentials and scheduler environment...
python scripts\run_scheduler.py --validate
if errorlevel 1 (
    echo.
    echo [WARNING] Validation reported an issue. Check output above or dashboard logs.
    pause
    exit /b 1
)

echo.
echo Checking scheduler and dashboard startup status (no duplicate processes)...
python scripts\manage_windows_task.py boot

echo.
echo [SUCCESS] CurioLoop YouTube authorization refreshed and verified.
pause
endlocal
