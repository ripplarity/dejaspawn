"""Install or remove a recurring drill (Windows Scheduled Task or cron line)."""

import os
import subprocess
import sys

NAME = "dejaspawn-drill"


def command():
    # --dry-run: a scheduled run never sends a DNS import
    return f'"{sys.executable}" -m dejaspawn drill --card --dry-run'


def plan(freq, windows=None, cwd=None):
    windows = (os.name == "nt") if windows is None else windows
    cwd = cwd or os.getcwd()
    if windows:
        sc = "MONTHLY" if freq == "monthly" else "WEEKLY"
        tr = f'cmd /c cd /d "{cwd}" && {command()}'
        return "windows", [
            "schtasks",
            "/Create",
            "/TN",
            NAME,
            "/SC",
            sc,
            "/TR",
            tr,
            "/F",
        ]
    when = "0 3 1 * *" if freq == "monthly" else "0 3 * * 1"
    return "cron", f'{when} cd "{cwd}" && {command()} # {NAME}'


def _cron_without_ours():
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    return [x for x in cur.splitlines() if NAME not in x]


def install(freq, dry_run=False):
    kind, spec = plan(freq)
    if kind == "windows":
        print("task:", " ".join(spec))
        return 0 if dry_run else subprocess.run(spec).returncode
    print("cron:", spec)
    if dry_run:
        return 0
    body = "\n".join(_cron_without_ours() + [spec]) + "\n"
    return subprocess.run(["crontab", "-"], input=body, text=True).returncode


def uninstall(dry_run=False):
    if os.name == "nt":
        cmd = ["schtasks", "/Delete", "/TN", NAME, "/F"]
        print("task:", " ".join(cmd))
        return 0 if dry_run else subprocess.run(cmd).returncode
    print(f"cron: remove lines tagged {NAME}")
    if dry_run:
        return 0
    body = "\n".join(_cron_without_ours()) + "\n"
    return subprocess.run(["crontab", "-"], input=body, text=True).returncode
