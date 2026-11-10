# ==============================================================================
# Curiosity Engine - Autonomous Local Scheduler PowerShell Launcher
# Starts the local scheduler daemon with Asia/Kolkata timezone awareness.
# ==============================================================================
[CmdletBinding()]
param (
    [switch]$Once,
    [switch]$DryRun,
    [switch]$Validate,
    [switch]$Status,
    [int]$Interval = 15
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "CurioLoop Studio - Autonomous Local Scheduler" -ForegroundColor Cyan
Write-Host "Project Root: $ProjectRoot"
Write-Host "Timezone: Asia/Kolkata (IST)"
Write-Host "==================================================" -ForegroundColor Cyan

if ($Status) {
    python scripts\run_scheduler.py --status
    exit $LASTEXITCODE
}

if ($DryRun) {
    python scripts\run_scheduler.py --dry-run
    exit $LASTEXITCODE
}

if ($Validate) {
    python scripts\run_scheduler.py --validate
    exit $LASTEXITCODE
}

if ($Once) {
    Write-Host "Running single catch-up evaluation..." -ForegroundColor Yellow
    python scripts\run_scheduler.py --once --confirm
    exit $LASTEXITCODE
}

Write-Host "Launching local scheduler daemon (polling every ${Interval}s)..." -ForegroundColor Green
python scripts\run_scheduler.py --daemon --interval $Interval
