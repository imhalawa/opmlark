from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from article_importer.workspace import WorkspaceError


@dataclass(frozen=True)
class ScheduleInfo:
    platform: str
    name: str
    time: str
    command: str


def schedule_info(config_path: Path, time: str = "07:00") -> ScheduleInfo:
    hour, minute = _time_parts(time)
    executable = shutil.which("opmlark")
    if executable is None:
        raise WorkspaceError(
            "Scheduling requires a stable global command; run `npm install --global opmlark` first"
        )
    command = f'{_quote(executable)} run --config {_quote(str(config_path.resolve()))}'
    name = f"OPMLark - {config_path.parent.name}"
    return ScheduleInfo("windows" if os.name == "nt" else "cron", name, f"{hour:02d}:{minute:02d}", command)


def install_schedule(config_path: Path, time: str = "07:00") -> ScheduleInfo:
    info = schedule_info(config_path, time)
    if os.name == "nt":
        result = subprocess.run(
            [
                "schtasks.exe",
                "/Create",
                "/SC",
                "DAILY",
                "/TN",
                info.name,
                "/TR",
                info.command,
                "/ST",
                info.time,
                "/F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or result.stdout.strip())
        return info

    marker = _cron_marker(config_path)
    current = _read_crontab()
    retained = [line for line in current.splitlines() if marker not in line]
    hour, minute = _time_parts(time)
    log_path = config_path.parent / "data" / "scheduler.log"
    line = f"{minute} {hour} * * * {info.command} >> {_quote(str(log_path))} 2>&1 {marker}"
    contents = "\n".join(retained + [line]).strip() + "\n"
    _write_crontab(contents)
    return info


def remove_schedule(config_path: Path) -> ScheduleInfo:
    info = schedule_info(config_path)
    if os.name == "nt":
        result = subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", info.name, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or result.stdout.strip())
        return info

    marker = _cron_marker(config_path)
    current = _read_crontab()
    contents = "\n".join(line for line in current.splitlines() if marker not in line)
    _write_crontab(contents.strip() + ("\n" if contents.strip() else ""))
    return info


def _time_parts(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, TypeError) as error:
        raise WorkspaceError("Schedule time must use HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise WorkspaceError("Schedule time must use a valid 24-hour HH:MM value")
    return hour, minute


def _cron_marker(config_path: Path) -> str:
    digest = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:12]
    return f"# opmlark:{digest}"


def _read_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if result.returncode and "no crontab" not in result.stderr.lower():
        raise WorkspaceError(result.stderr.strip() or "Unable to read crontab")
    return result.stdout


def _write_crontab(contents: str) -> None:
    result = subprocess.run(
        ["crontab", "-"], input=contents, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise WorkspaceError(result.stderr.strip() or "Unable to update crontab")


def _quote(value: str) -> str:
    if os.name == "nt":
        return f'"{value}"' if " " in value else value
    return shlex.quote(value)
