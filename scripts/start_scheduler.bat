@echo off
REM ==============================================================================
REM Curiosity Engine - Autonomous Local Scheduler Windows Launcher
REM Starts the local scheduler daemon in the background or active console.
REM Strict ₹0 Target: No cloud resources or billing.
REM ==============================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0\.."

echo [CurioLoop Studio] Starting Curiosity Engine Autonomous Scheduler...
echo Workspace: %CD%
echo Timezone: Asia/Kolkata (IST)

if "%1"=="--once" (
    echo Running single catch-up check with explicit confirmation...
    python scripts\run_scheduler.py --once --confirm
    exit /b %ERRORLEVEL%
)

if "%1"=="--dry-run" (
    python scripts\run_scheduler.py --dry-run
    exit /b %ERRORLEVEL%
)

if "%1"=="--validate" (
    python scripts\run_scheduler.py --validate
    exit /b %ERRORLEVEL%
)

if "%1"=="--status" (
    python scripts\run_scheduler.py --status
    exit /b %ERRORLEVEL%
)

echo Launching scheduler daemon...
python scripts\run_scheduler.py --daemon --interval 15
