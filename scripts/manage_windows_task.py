"""CurioLoop Windows Startup Automation & Task Manager.
Manages Windows Task Scheduler registration, user logon startup,
service inspection, process control, and persistent execution logging.

Usage:
    python scripts/manage_windows_task.py register         # Register single Windows Startup .vbs launcher (scheduler + dashboard)
    python scripts/manage_windows_task.py unregister       # Remove Windows startup automation
    python scripts/manage_windows_task.py status           # Query registration, scheduler daemon, and dashboard status
    python scripts/manage_windows_task.py boot             # Start both scheduler & dashboard independently (idempotent)
    python scripts/manage_windows_task.py start            # Start scheduler daemon
    python scripts/manage_windows_task.py stop             # Safely stop scheduler daemon
    python scripts/manage_windows_task.py restart          # Restart scheduler daemon
    python scripts/manage_windows_task.py start-dashboard  # Start dashboard server independently
    python scripts/manage_windows_task.py stop-dashboard   # Stop dashboard server
    python scripts/manage_windows_task.py stop-all         # Stop both scheduler daemon and dashboard
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from curiosity_engine.config import DASHBOARD_HOST, DASHBOARD_PORT, DATA_DIR, get_hidden_subprocess_kwargs
from curiosity_engine.runner.local_scheduler import SCHEDULER_LOCK_FILE, LocalScheduler

TASK_NAME = "CurioLoopScheduler"
IST = ZoneInfo("Asia/Kolkata")
LOG_FILE = DATA_DIR / "scheduler.log"
SCHEDULER_CONSOLE_LOG_FILE = DATA_DIR / "scheduler_console.log"
DASHBOARD_LOCK_FILE = DATA_DIR / ".dashboard.lock"
DASHBOARD_LOG_FILE = DATA_DIR / "dashboard.log"
STARTUP_LOG_FILE = DATA_DIR / "startup.log"
XML_TASK_FILE = DATA_DIR / "CurioLoopScheduler.xml"


def _append_startup_log(message: str) -> None:
    """Append a timestamped IST line to data/startup.log."""
    try:
        STARTUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        with open(STARTUP_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def is_port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    """Check whether a local TCP port is actively accepting connections."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


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
    Uses a single Startup-folder VBS launcher invoking `manage_windows_task.py boot`
    so both the autonomous scheduler daemon and web dashboard start cleanly and idempotently.
    """
    pythonw = get_pythonw_path()
    manage_script = PROJECT_ROOT / "scripts" / "manage_windows_task.py"
    run_script = PROJECT_ROOT / "scripts" / "run_scheduler.py"
    work_dir = PROJECT_ROOT
    vbs_path = get_startup_vbs_path()

    if not pythonw.exists():
        return {"success": False, "error": f"Python executable not found: {pythonw}"}
    if not manage_script.exists():
        return {"success": False, "error": f"Startup manager script not found: {manage_script}"}
    if not run_script.exists():
        return {"success": False, "error": f"Scheduler script not found: {run_script}"}

    # 1. Single active startup mechanism: User Startup VBS Launcher (no admin rights needed)
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{work_dir}"\n'
        f'WshShell.Run """{pythonw}"" ""{manage_script}"" boot", 0, False\n'
    )
    vbs_path.write_text(vbs_content, encoding="utf-8")
    vbs_registered = vbs_path.exists()

    # Keep XML specification updated for documentation/optional admin override, but do NOT create competing schtask
    xml_content = generate_task_xml(pythonw, manage_script, work_dir)
    XML_TASK_FILE.write_text(xml_content, encoding="utf-16")

    # Ensure no competing Task Scheduler entry is left active
    schtasks_removed_duplicate = False
    try:
        q = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME], capture_output=True, text=True, **get_hidden_subprocess_kwargs())
        if q.returncode == 0:
            subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True, text=True, **get_hidden_subprocess_kwargs())
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
        "arguments": f'"{manage_script}" boot',
        "log_path": str(LOG_FILE),
        "dashboard_url": f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}",
        "dashboard_log_path": str(DASHBOARD_LOG_FILE),
        "startup_log_path": str(STARTUP_LOG_FILE),
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
        res = subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True, text=True, **get_hidden_subprocess_kwargs())
        if res.returncode == 0:
            schtasks_removed = True
    except Exception:
        pass

    return {
        "success": True,
        "vbs_removed": vbs_removed,
        "schtasks_removed": schtasks_removed,
    }


def get_dashboard_status() -> Dict[str, Any]:
    """Inspect whether the local web dashboard server is running (lock PID + port check)."""
    sched = LocalScheduler()
    pid_alive = False
    running_pid: Optional[int] = None
    if DASHBOARD_LOCK_FILE.exists():
        try:
            pid_str = DASHBOARD_LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                pid = int(pid_str)
                if sched._is_pid_alive(pid):
                    pid_alive = True
                    running_pid = pid
                else:
                    # Clean up stale lock from dead or non-python recycled PID
                    try:
                        DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass

    port_open = is_port_open(DASHBOARD_HOST, DASHBOARD_PORT)
    is_running = bool(port_open)
    return {
        "is_running": is_running,
        "pid_alive": pid_alive,
        "running_pid": running_pid,
        "port_open": port_open,
        "host": DASHBOARD_HOST,
        "port": DASHBOARD_PORT,
        "url": f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}",
        "log_path": str(DASHBOARD_LOG_FILE),
        "log_exists": DASHBOARD_LOG_FILE.exists(),
    }


def get_task_status() -> Dict[str, Any]:
    """Query current status of startup registration and background processes (scheduler + dashboard)."""
    vbs_path = get_startup_vbs_path()
    vbs_exists = vbs_path.exists()

    schtasks_status = "NOT_REGISTERED"
    try:
        res = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"], capture_output=True, text=True, **get_hidden_subprocess_kwargs())
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

    dash = get_dashboard_status()

    return {
        "task_name": TASK_NAME,
        "startup_vbs_registered": vbs_exists,
        "startup_vbs_path": str(vbs_path) if vbs_exists else None,
        "schtasks_status": schtasks_status,
        "is_daemon_running": is_running,
        "running_pid": running_pid,
        "log_path": str(LOG_FILE),
        "log_exists": LOG_FILE.exists(),
        "dashboard_running": dash["is_running"],
        "dashboard_pid": dash["running_pid"],
        "dashboard_port_open": dash["port_open"],
        "dashboard_url": dash["url"],
        "dashboard_log_path": dash["log_path"],
        "dashboard_log_exists": dash["log_exists"],
        "startup_log_path": str(STARTUP_LOG_FILE),
    }


def start_daemon_background() -> Dict[str, Any]:
    """Launch scheduler daemon in background without opening console windows."""
    status = get_task_status()
    if status["is_daemon_running"]:
        msg = f"Scheduler daemon already running (PID: {status['running_pid']})."
        _append_startup_log(f"SKIP scheduler: {msg}")
        return {
            "success": True,
            "already_running": True,
            "message": msg,
            "pid": status["running_pid"],
        }

    if SCHEDULER_LOCK_FILE.exists():
        try:
            SCHEDULER_LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    pythonw = get_pythonw_path()
    run_script = PROJECT_ROOT / "scripts" / "run_scheduler.py"

    # Launch detached process with --daemon explicitly and redirected output (safe under pythonw.exe)
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    hidden_kw = get_hidden_subprocess_kwargs()
    creationflags = DETACHED_PROCESS | hidden_kw.get("creationflags", CREATE_NO_WINDOW)
    startupinfo = hidden_kw.get("startupinfo")

    SCHEDULER_CONSOLE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(SCHEDULER_CONSOLE_LOG_FILE, "a", encoding="utf-8")
    try:
        popen_kwargs: Dict[str, Any] = {
            "cwd": str(PROJECT_ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh,
            "stderr": log_fh,
            "creationflags": creationflags,
            "close_fds": True,
        }
        if startupinfo is not None:
            popen_kwargs["startupinfo"] = startupinfo
        proc = subprocess.Popen(
            [str(pythonw), str(run_script), "--daemon", "--interval", "15"],
            **popen_kwargs,
        )
    finally:
        log_fh.close()

    _append_startup_log(f"STARTED scheduler daemon PID={proc.pid}")
    return {
        "success": True,
        "already_running": False,
        "message": f"Scheduler started in background (PID: {proc.pid}).",
        "pid": proc.pid,
    }


def start_dashboard_background() -> Dict[str, Any]:
    """Launch CurioLoop web dashboard detached under pythonw.exe without duplicates."""
    dash = get_dashboard_status()
    if dash["is_running"]:
        msg = f"Dashboard already running on {dash['url']} (PID: {dash['running_pid']}, port_open={dash['port_open']})."
        _append_startup_log(f"SKIP dashboard: {msg}")
        return {
            "success": True,
            "already_running": True,
            "message": msg,
            "pid": dash["running_pid"],
            "url": dash["url"],
        }

    if DASHBOARD_LOCK_FILE.exists():
        try:
            DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    pythonw = get_pythonw_path()
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    hidden_kw = get_hidden_subprocess_kwargs()
    creationflags = DETACHED_PROCESS | hidden_kw.get("creationflags", CREATE_NO_WINDOW)
    startupinfo = hidden_kw.get("startupinfo")

    DASHBOARD_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(DASHBOARD_LOG_FILE, "a", encoding="utf-8")
    try:
        popen_kwargs: Dict[str, Any] = {
            "cwd": str(PROJECT_ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh,
            "stderr": log_fh,
            "creationflags": creationflags,
            "close_fds": True,
        }
        if startupinfo is not None:
            popen_kwargs["startupinfo"] = startupinfo
        proc = subprocess.Popen(
            [
                str(pythonw),
                "-m",
                "uvicorn",
                "curiosity_engine.dashboard.app:app",
                "--host",
                DASHBOARD_HOST,
                "--port",
                str(DASHBOARD_PORT),
                "--log-level",
                "info",
                "--no-use-colors",
            ],
            **popen_kwargs,
        )
    finally:
        log_fh.close()

    try:
        DASHBOARD_LOCK_FILE.write_text(str(proc.pid), encoding="utf-8")
    except Exception:
        pass

    # Brief readiness wait so port status reflects live health cleanly
    for _ in range(10):
        if is_port_open(DASHBOARD_HOST, DASHBOARD_PORT, timeout=0.4):
            break
        if proc.poll() is not None:
            _append_startup_log(f"ERROR dashboard exited prematurely code={proc.returncode}")
            return {
                "success": False,
                "already_running": False,
                "message": f"Dashboard failed to stay running (exit code {proc.returncode}). Check {DASHBOARD_LOG_FILE}",
                "pid": proc.pid,
                "url": dash["url"],
            }
        time.sleep(0.3)

    _append_startup_log(f"STARTED dashboard server PID={proc.pid} on {dash['url']}")
    return {
        "success": True,
        "already_running": False,
        "message": f"Dashboard started in background (PID: {proc.pid}) at {dash['url']}.",
        "pid": proc.pid,
        "url": dash["url"],
    }


def stop_dashboard() -> Dict[str, Any]:
    """Stop running local dashboard process cleanly via PID lock."""
    dash = get_dashboard_status()
    pid = dash.get("running_pid")
    if not dash.get("pid_alive") or not pid:
        if DASHBOARD_LOCK_FILE.exists():
            DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
        return {
            "success": True,
            "message": "Dashboard is not tracked by lockfile." if not dash.get("port_open") else f"Port {DASHBOARD_PORT} open without lock PID.",
        }

    sched = LocalScheduler()
    if not sched._is_pid_alive(pid):
        DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
        return {"success": True, "message": "Dashboard process was not alive or not Python; cleared lock."}

    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, **get_hidden_subprocess_kwargs())
    except Exception:
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    for _ in range(10):
        if not sched._is_pid_alive(pid):
            break
        time.sleep(0.3)

    DASHBOARD_LOCK_FILE.unlink(missing_ok=True)
    _append_startup_log(f"STOPPED dashboard PID={pid}")
    return {"success": True, "message": f"Dashboard (PID: {pid}) stopped cleanly."}


def boot_all() -> Dict[str, Any]:
    """Independently launch both scheduler daemon and web dashboard at startup/login.
    Failure of either service never prevents the other from starting.
    """
    _append_startup_log("=== CurioLoop Boot Sequence Initiated ===")
    try:
        sched_res = start_daemon_background()
    except Exception as exc:
        sched_res = {"success": False, "error": str(exc)}
        _append_startup_log(f"ERROR scheduler boot exception: {exc}")

    try:
        dash_res = start_dashboard_background()
    except Exception as exc:
        dash_res = {"success": False, "error": str(exc)}
        _append_startup_log(f"ERROR dashboard boot exception: {exc}")

    return {
        "success": bool(sched_res.get("success")) and bool(dash_res.get("success")),
        "scheduler": sched_res,
        "dashboard": dash_res,
        "startup_log": str(STARTUP_LOG_FILE),
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
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, **get_hidden_subprocess_kwargs())
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
    parser.add_argument(
        "action",
        choices=[
            "register",
            "unregister",
            "status",
            "boot",
            "start",
            "stop",
            "restart",
            "start-dashboard",
            "stop-dashboard",
            "stop-all",
        ],
    )
    args = parser.parse_args()

    if args.action == "register":
        res = register_task()
    elif args.action == "unregister":
        res = unregister_task()
    elif args.action == "status":
        res = get_task_status()
    elif args.action == "boot":
        res = boot_all()
    elif args.action == "start":
        res = start_daemon_background()
    elif args.action == "stop":
        res = stop_daemon()
    elif args.action == "restart":
        stop_daemon()
        time.sleep(1)
        res = start_daemon_background()
    elif args.action == "start-dashboard":
        res = start_dashboard_background()
    elif args.action == "stop-dashboard":
        res = stop_dashboard()
    elif args.action == "stop-all":
        res = {
            "scheduler": stop_daemon(),
            "dashboard": stop_dashboard(),
        }

    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
