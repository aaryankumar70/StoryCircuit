"""CurioLoop Windows Startup Automation & Task Manager.
Manages Windows Task Scheduler registration, user logon startup,
service inspection, process control, and persistent execution logging.

Usage:
    python scripts/manage_windows_task.py register     # Register Windows startup automation
    python scripts/manage_windows_task.py unregister   # Remove Windows startup automation
    python scripts/manage_windows_task.py status       # Query current registration & process status
    python scripts/manage_windows_task.py start        # Start scheduler daemon
    python scripts/manage_windows_task.py stop         # Safely stop scheduler daemon
    python scripts/manage_windows_task.py restart      # Restart scheduler daemon
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import DATA_DIR
from curiosity_engine.runner.local_scheduler import SCHEDULER_LOCK_FILE, LocalScheduler

TASK_NAME = "CurioLoopScheduler"
LOG_FILE = DATA_DIR / "scheduler.log"
XML_TASK_FILE = DATA_DIR / "CurioLoopScheduler.xml"


def get_pythonw_path() -> Path:
    """Find background pythonw.exe or python.exe."""
    py_dir = Path(sys.executable).parent
    pythonw = py_dir / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    return Path(sys.executable)


def get_startup_vbs_path() -> Path:
    """Get path to user Startup folder .vbs launcher."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    return startup_dir / "CurioLoopScheduler.vbs"


def generate_task_xml(python_exe: Path, script_path: Path, work_dir: Path) -> str:
    """Generate Windows Task Scheduler XML specification."""
    username = os.environ.get("USERNAME", "USER")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>CurioLoop Autonomous Production &amp; YouTube Publishing Scheduler</Description>
    <Author>{username}</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT1M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{script_path}"</Arguments>
      <WorkingDirectory>{work_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def register_task() -> Dict[str, Any]:
    """Register CurioLoop for automatic non-admin startup upon Windows user logon.
    Uses a single Startup-folder VBS launcher (passing --daemon) so two competing
    startup mechanisms are never active simultaneously.
    """
    pythonw = get_pythonw_path()
    run_script = PROJECT_ROOT / "scripts" / "run_scheduler.py"
    work_dir = PROJECT_ROOT
    vbs_path = get_startup_vbs_path()

    if not pythonw.exists():
        return {"success": False, "error": f"Python executable not found: {pythonw}"}
    if not run_script.exists():
        return {"success": False, "error": f"Scheduler script not found: {run_script}"}

    # 1. Single active startup mechanism: User Startup VBS Launcher (no admin rights needed)
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{work_dir}"\n'
        f'WshShell.Run """{pythonw}"" ""{run_script}"" --daemon", 0, False\n'
    )
    vbs_path.write_text(vbs_content, encoding="utf-8")
    vbs_registered = vbs_path.exists()

    # Keep XML specification updated for documentation/optional admin override, but do NOT create competing schtask
    xml_content = generate_task_xml(pythonw, run_script, work_dir)
    XML_TASK_FILE.write_text(xml_content, encoding="utf-16")

    # Ensure no competing Task Scheduler entry is left active
    schtasks_removed_duplicate = False
    try:
        q = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME], capture_output=True, text=True)
        if q.returncode == 0:
            subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True, text=True)
            schtasks_removed_duplicate = True
    except Exception:
        pass

    return {
        "success": vbs_registered,
        "task_name": TASK_NAME,
        "mechanism": "STARTUP_VBS_ONLY",
        "startup_vbs": str(vbs_path),
        "vbs_registered": vbs_registered,
        "schtasks_registered": False,
        "competing_schtask_removed": schtasks_removed_duplicate,
        "python_executable": str(pythonw),
        "working_directory": str(work_dir),
        "arguments": f'"{run_script}" --daemon',
        "log_path": str(LOG_FILE),
    }


def unregister_task() -> Dict[str, Any]:
    """Unregister task from Task Scheduler and remove startup vbs."""
    vbs_path = get_startup_vbs_path()
    vbs_removed = False
    if vbs_path.exists():
        vbs_path.unlink()
        vbs_removed = True

    schtasks_removed = False
    try:
        res = subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True, text=True)
        if res.returncode == 0:
            schtasks_removed = True
    except Exception:
        pass

    return {
        "success": True,
        "vbs_removed": vbs_removed,
        "schtasks_removed": schtasks_removed,
    }


def get_task_status() -> Dict[str, Any]:
    """Query current status of startup registration and background process."""
    vbs_path = get_startup_vbs_path()
    vbs_exists = vbs_path.exists()

    schtasks_status = "NOT_REGISTERED"
    try:
        res = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"], capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("Status:"):
                    schtasks_status = line.split(":", 1)[1].strip()
                    break
            if schtasks_status == "NOT_REGISTERED":
                schtasks_status = "REGISTERED"
    except Exception:
        schtasks_status = "ERROR"

    # Process status
    sched = LocalScheduler()
    is_running = False
    running_pid = None
    if SCHEDULER_LOCK_FILE.exists():
        try:
            pid_str = SCHEDULER_LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                if sched._is_pid_alive(pid):
                    is_running = True
                    running_pid = pid
        except Exception:
            pass

    return {
        "task_name": TASK_NAME,
        "startup_vbs_registered": vbs_exists,
        "startup_vbs_path": str(vbs_path) if vbs_exists else None,
        "schtasks_status": schtasks_status,
        "is_daemon_running": is_running,
        "running_pid": running_pid,
        "log_path": str(LOG_FILE),
        "log_exists": LOG_FILE.exists(),
    }


def start_daemon_background() -> Dict[str, Any]:
    """Launch scheduler daemon in background without opening console windows."""
    status = get_task_status()
    if status["is_daemon_running"]:
        return {
            "success": True,
            "message": f"Scheduler daemon already running (PID: {status['running_pid']}).",
            "pid": status["running_pid"],
        }

    pythonw = get_pythonw_path()
    run_script = PROJECT_ROOT / "scripts" / "run_scheduler.py"

    # Launch detached process with --daemon explicitly
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    creationflags = DETACHED_PROCESS | CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [str(pythonw), str(run_script), "--daemon"],
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
        close_fds=True,
    )

    return {
        "success": True,
        "message": f"Scheduler started in background (PID: {proc.pid}).",
        "pid": proc.pid,
    }


def stop_daemon() -> Dict[str, Any]:
    """Gracefully stop running scheduler daemon via .scheduler.stop signal, falling back to terminate."""
    import time
    from curiosity_engine.runner.local_scheduler import SCHEDULER_STOP_FILE

    status = get_task_status()
    if not status["is_daemon_running"]:
        if SCHEDULER_LOCK_FILE.exists():
            SCHEDULER_LOCK_FILE.unlink(missing_ok=True)
        return {"success": True, "message": "Scheduler daemon is not currently running."}

    pid = status["running_pid"]
    sched = LocalScheduler()

    # 1. Request graceful shutdown so daemon exits loop and releases lock cleanly
    try:
        SCHEDULER_STOP_FILE.write_text("stop", encoding="utf-8")
    except Exception:
        pass

    for _ in range(10):
        if not pid or not sched._is_pid_alive(pid):
            break
        time.sleep(0.5)

    # 2. Fallback forced termination only if daemon did not exit gracefully within 5s
    if pid and sched._is_pid_alive(pid):
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
        except Exception:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            except Exception:
                pass
        time.sleep(0.5)

    if SCHEDULER_LOCK_FILE.exists():
        try:
            SCHEDULER_LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    if SCHEDULER_STOP_FILE.exists():
        try:
            SCHEDULER_STOP_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    return {"success": True, "message": f"Scheduler daemon (PID: {pid}) stopped cleanly."}


def main():
    parser = argparse.ArgumentParser(description="CurioLoop Windows Startup Task Manager")
    parser.add_argument("action", choices=["register", "unregister", "status", "start", "stop", "restart"])
    args = parser.parse_args()

    if args.action == "register":
        res = register_task()
    elif args.action == "unregister":
        res = unregister_task()
    elif args.action == "status":
        res = get_task_status()
    elif args.action == "start":
        res = start_daemon_background()
    elif args.action == "stop":
        res = stop_daemon()
    elif args.action == "restart":
        stop_daemon()
        import time
        time.sleep(1)
        res = start_daemon_background()

    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
