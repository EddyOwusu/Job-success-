"""Set up the agent's timetable on Windows (Task Scheduler) or Mac/Linux (cron)."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

# (task name, schedule, arguments, what it's for)
TASKS = [
    ("jobstream-daily", ("DAILY", "07:10"), "run --mode pack", "full run: search, assess, build packs, digest"),
    ("jobstream-watch-1", ("DAILY", "11:30"), "watch", "quick check for fresh jobs"),
    ("jobstream-watch-2", ("DAILY", "15:30"), "watch", "quick check for fresh jobs"),
    ("jobstream-watch-3", ("DAILY", "19:30"), "watch", "quick check for fresh jobs"),
    ("jobstream-weekly", ("WEEKLY", "06:40"), "discover", "find more sponsor job boards (Mondays)"),
]
MARK = "# jobstream"


def executable() -> str:
    exe = shutil.which("jobstream")
    if exe:
        return exe
    return f'"{sys.executable}" -m jobstream'


def windows_commands() -> list[str]:
    exe = executable()
    out = []
    for name, (freq, at), args, _ in TASKS:
        tr = f'{exe} {args}' if exe.startswith('"') else f'\\"{exe}\\" {args}'
        cmd = f'schtasks /Create /F /TN "{name}" /SC {freq} /ST {at} /TR "{tr}"'
        if freq == "WEEKLY":
            cmd += " /D MON"
        out.append(cmd)
    return out


def cron_lines(log: Path) -> list[str]:
    exe = executable()
    out = []
    for _name, (freq, at), args, _ in TASKS:
        hh, mm = at.split(":")
        dow = "1" if freq == "WEEKLY" else "*"
        out.append(f"{int(mm)} {int(hh)} * * {dow} {exe} {args} >> {log} 2>&1 {MARK}")
    return out


def plan(log: Path) -> tuple[str, list[str]]:
    if platform.system() == "Windows":
        return "windows", windows_commands()
    return "cron", cron_lines(log)


def install(log: Path) -> str:
    kind, lines = plan(log)
    if kind == "windows":
        for cmd in lines:
            subprocess.run(cmd, shell=True, check=True)
        return f"Created {len(lines)} tasks in Windows Task Scheduler. Your PC must be on (not asleep) at those times."
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    keep = [l for l in (current.stdout or "").splitlines() if MARK not in l]
    subprocess.run(["crontab", "-"], input="\n".join(keep + lines) + "\n", text=True, check=True)
    return f"Added {len(lines)} lines to your crontab (existing jobstream lines were replaced)."


def remove() -> str:
    if platform.system() == "Windows":
        for name, *_ in TASKS:
            subprocess.run(f'schtasks /Delete /F /TN "{name}"', shell=True)
        return "Removed the jobstream tasks from Windows Task Scheduler."
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    keep = [l for l in (current.stdout or "").splitlines() if MARK not in l]
    subprocess.run(["crontab", "-"], input="\n".join(keep) + ("\n" if keep else ""), text=True, check=True)
    return "Removed the jobstream lines from your crontab."
