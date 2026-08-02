from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
import hashlib
from io import StringIO
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile

from article_importer.configuration import Schedule, load_config
from article_importer.schedule_config import (
    add_schedule_config,
    edit_schedule_config,
    remove_schedule_config,
)
from article_importer.workspace import WorkspaceError


@dataclass(frozen=True)
class ScheduleInfo:
    platform: str
    name: str
    time: str
    command: str
    id: str = "default"
    expression: str = "daily"
    enabled: bool = True
    artifact: str | None = None


@dataclass(frozen=True)
class ScheduleChange:
    id: str
    action: str
    ok: bool = True
    detail: str = ""


def schedule_info(
    config_path: Path, schedule: Schedule | str = "07:00"
) -> ScheduleInfo:
    if isinstance(schedule, str):
        _time_parts(schedule)
        schedule = Schedule("default", "daily", schedule)
    executable = shutil.which("opmlark")
    if executable is None:
        raise WorkspaceError(
            "Scheduling requires a stable global command; run `npm install --global opmlark` first"
        )
    if _is_temporary_npx_path(executable):
        raise WorkspaceError(
            "Scheduling cannot use a temporary npx command; run `npm install --global opmlark` first"
        )
    arguments = f'run --config {_quote(str(config_path.resolve()))}'
    if _platform() == "windows" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        command = f'cmd.exe /D /C ""{executable}" {arguments}"'
    else:
        command = f"{_quote(executable)} {arguments}"
    digest = _workspace_digest(config_path)
    platform = _platform()
    if platform == "windows":
        name = f"OPMLark - {config_path.parent.name} - {digest} - {schedule.id}"
        artifact = name
    elif platform == "launchd":
        name = f"io.opmlark.{digest}.{schedule.id}"
        artifact = str(_launchd_directory() / f"{name}.plist")
    else:
        name = f"OPMLark - {config_path.parent.name} - {digest} - {schedule.id}"
        artifact = _cron_marker(config_path, schedule.id)
    return ScheduleInfo(
        platform,
        name,
        schedule.at,
        command,
        schedule.id,
        _describe(schedule),
        schedule.enabled,
        artifact,
    )


def windows_create_arguments(info: ScheduleInfo, schedule: Schedule) -> list[str]:
    arguments = [
        "schtasks.exe",
        "/Create",
        "/TN",
        info.name,
        "/TR",
        info.command,
        "/SC",
        schedule.frequency.upper(),
    ]
    if schedule.frequency == "weekly":
        arguments.extend(["/D", ",".join(day.upper() for day in schedule.days)])
    elif schedule.frequency == "monthly":
        arguments.extend(["/D", str(schedule.day)])
    elif schedule.frequency == "once":
        arguments.extend(["/SD", str(schedule.date)])
    arguments.extend(["/ST", schedule.at, "/F"])
    return arguments


def cron_line(config_path: Path, schedule: Schedule, info: ScheduleInfo) -> str:
    hour, minute = _time_parts(schedule.at)
    if schedule.frequency == "daily":
        fields = f"{minute} {hour} * * *"
    elif schedule.frequency == "weekly":
        fields = f"{minute} {hour} * * {','.join(schedule.days)}"
    elif schedule.frequency == "monthly":
        fields = f"{minute} {hour} {schedule.day} * *"
    else:
        scheduled_date = date.fromisoformat(str(schedule.date))
        fields = f"{minute} {hour} {scheduled_date.day} {scheduled_date.month} *"
    command = info.command
    if schedule.frequency == "once":
        command = (
            f'[ "$(date +\\%Y-\\%m-\\%d)" = "{schedule.date}" ] && {command}'
        )
    log_path = config_path.parent / "data" / "scheduler.log"
    return (
        f"{fields} {command} >> {_quote(str(log_path.resolve()))} 2>&1 "
        f"{_cron_marker(config_path, schedule.id)}"
    )


def launchd_plist(config_path: Path, schedule: Schedule, info: ScheduleInfo) -> bytes:
    hour, minute = _time_parts(schedule.at)
    interval: dict[str, int] | list[dict[str, int]]
    base = {"Hour": hour, "Minute": minute}
    if schedule.frequency == "daily":
        interval = base
    elif schedule.frequency == "weekly":
        weekday = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
        interval = [{**base, "Weekday": weekday[item]} for item in schedule.days]
    elif schedule.frequency == "monthly":
        interval = {**base, "Day": int(schedule.day)}
    else:
        scheduled_date = date.fromisoformat(str(schedule.date))
        interval = {
            "Month": scheduled_date.month,
            "Day": scheduled_date.day,
            **base,
        }
    log_path = (config_path.parent / "data" / "scheduler.log").resolve()
    command = f"{info.command} >> {shlex.quote(str(log_path))} 2>&1"
    if schedule.frequency == "once":
        command = f'test "$(date +%F)" = "{schedule.date}" && {command}'
    payload = {
        "Label": info.name,
        "ProgramArguments": ["/bin/sh", "-c", command],
        "StartCalendarInterval": interval,
    }
    return plistlib.dumps(payload, sort_keys=True)


def schedule_status(config_path: Path) -> tuple[ScheduleChange, ...]:
    schedules = load_config(config_path).schedules
    platform = _platform()
    if platform == "cron":
        current = _cron_entries(config_path, _read_crontab())
        desired_ids = {item.id for item in schedules}
        statuses = []
        for schedule in schedules:
            if not schedule.enabled:
                action = "disabled"
            else:
                expected = cron_line(config_path, schedule, schedule_info(config_path, schedule))
                action = "installed" if current.get(schedule.id) == expected else (
                    "drifted" if schedule.id in current else "missing"
                )
            statuses.append(ScheduleChange(schedule.id, action))
        statuses.extend(
            ScheduleChange(schedule_id, "stale")
            for schedule_id in sorted(set(current) - desired_ids)
        )
        return tuple(statuses)
    if platform == "launchd":
        current = _launchd_managed(config_path)
        desired_ids = {item.id for item in schedules}
        statuses = []
        for schedule in schedules:
            if not schedule.enabled:
                action = "disabled"
            else:
                expected = launchd_plist(config_path, schedule, schedule_info(config_path, schedule))
                path = current.get(schedule.id)
                action = "missing" if path is None else (
                    "installed" if path.read_bytes() == expected else "drifted"
                )
            statuses.append(ScheduleChange(schedule.id, action))
        statuses.extend(
            ScheduleChange(schedule_id, "stale")
            for schedule_id in sorted(set(current) - desired_ids)
        )
        return tuple(statuses)

    current = _windows_managed(config_path)
    desired_ids = {item.id for item in schedules}
    statuses = [
        ScheduleChange(
            schedule.id,
            "disabled" if not schedule.enabled else (
                "installed" if schedule.id in current else "missing"
            ),
        )
        for schedule in schedules
    ]
    statuses.extend(
        ScheduleChange(schedule_id, "stale")
        for schedule_id in sorted(set(current) - desired_ids)
    )
    return tuple(statuses)


def apply_schedules(config_path: Path) -> tuple[ScheduleChange, ...]:
    platform = _platform()
    if platform == "cron":
        return _apply_cron(config_path)
    if platform == "launchd":
        return _apply_launchd(config_path)
    return _apply_windows(config_path)


def install_schedule(config_path: Path, time: str = "07:00") -> ScheduleInfo:
    schedule = Schedule("default", "daily", time)
    existing = {item.id: item for item in load_config(config_path).schedules}
    if "default" in existing:
        edit_schedule_config(config_path, "default", schedule)
    else:
        add_schedule_config(config_path, schedule)
    changes = apply_schedules(config_path)
    failure = next((item for item in changes if item.id == "default" and not item.ok), None)
    if failure:
        raise WorkspaceError(failure.detail)
    return schedule_info(config_path, schedule)


def remove_native_schedule(config_path: Path, schedule_id: str) -> ScheduleChange:
    schedule = next(
        (item for item in load_config(config_path).schedules if item.id == schedule_id),
        Schedule(schedule_id, "daily", "07:00"),
    )
    info = schedule_info(config_path, schedule)
    try:
        if _platform() == "windows":
            _run_checked(["schtasks.exe", "/Delete", "/TN", info.name, "/F"])
        elif _platform() == "launchd":
            path = Path(str(info.artifact))
            _launchctl_remove(path, info.name)
        else:
            current = _read_crontab()
            marker = _cron_marker(config_path, schedule_id)
            retained = [line for line in current.splitlines() if marker not in line]
            _write_crontab(_lines(retained))
        return ScheduleChange(schedule_id, "removed")
    except (OSError, WorkspaceError) as error:
        return ScheduleChange(schedule_id, "failed", False, str(error))


def remove_schedule(config_path: Path) -> ScheduleInfo:
    schedule = next(
        (item for item in load_config(config_path).schedules if item.id == "default"),
        Schedule("default", "daily", "07:00"),
    )
    info = schedule_info(config_path, schedule)
    change = remove_native_schedule(config_path, "default")
    if not change.ok:
        raise WorkspaceError(change.detail)
    if any(item.id == "default" for item in load_config(config_path).schedules):
        remove_schedule_config(config_path, "default")
    return info


def _apply_cron(config_path: Path) -> tuple[ScheduleChange, ...]:
    schedules = load_config(config_path).schedules
    current_text = _read_crontab()
    current = _cron_entries(config_path, current_text)
    desired_ids = {item.id for item in schedules}
    changes: list[ScheduleChange] = []
    new_lines = [
        line
        for line in current_text.splitlines()
        if not _is_workspace_cron_line(config_path, line)
    ]
    (config_path.parent / "data").mkdir(parents=True, exist_ok=True)
    for schedule in schedules:
        if not schedule.enabled:
            changes.append(
                ScheduleChange(schedule.id, "removed" if schedule.id in current else "disabled")
            )
            continue
        expected = cron_line(config_path, schedule, schedule_info(config_path, schedule))
        action = "unchanged" if current.get(schedule.id) == expected else (
            "updated" if schedule.id in current else "created"
        )
        changes.append(ScheduleChange(schedule.id, action))
        new_lines.append(expected)
    changes.extend(
        ScheduleChange(schedule_id, "removed")
        for schedule_id in sorted(set(current) - desired_ids)
    )
    contents = _lines(new_lines)
    if contents != current_text:
        _write_crontab(contents)
    return tuple(changes)


def _apply_windows(config_path: Path) -> tuple[ScheduleChange, ...]:
    schedules = load_config(config_path).schedules
    current = _windows_managed(config_path)
    desired_ids = {item.id for item in schedules}
    changes: list[ScheduleChange] = []
    for schedule in schedules:
        try:
            info = schedule_info(config_path, schedule)
            if schedule.enabled:
                _run_checked(windows_create_arguments(info, schedule))
                changes.append(
                    ScheduleChange(schedule.id, "updated" if schedule.id in current else "created")
                )
            elif schedule.id in current:
                _run_checked(["schtasks.exe", "/Delete", "/TN", current[schedule.id], "/F"])
                changes.append(ScheduleChange(schedule.id, "removed"))
            else:
                changes.append(ScheduleChange(schedule.id, "disabled"))
        except (OSError, WorkspaceError) as error:
            changes.append(ScheduleChange(schedule.id, "failed", False, str(error)))
    for schedule_id in sorted(set(current) - desired_ids):
        try:
            _run_checked(["schtasks.exe", "/Delete", "/TN", current[schedule_id], "/F"])
            changes.append(ScheduleChange(schedule_id, "removed"))
        except (OSError, WorkspaceError) as error:
            changes.append(ScheduleChange(schedule_id, "failed", False, str(error)))
    return tuple(changes)


def _apply_launchd(config_path: Path) -> tuple[ScheduleChange, ...]:
    schedules = load_config(config_path).schedules
    current = _launchd_managed(config_path)
    desired_ids = {item.id for item in schedules}
    changes: list[ScheduleChange] = []
    (config_path.parent / "data").mkdir(parents=True, exist_ok=True)
    for schedule in schedules:
        try:
            info = schedule_info(config_path, schedule)
            path = Path(str(info.artifact))
            if schedule.enabled:
                payload = launchd_plist(config_path, schedule, info)
                existed = path.exists()
                _atomic_bytes(path, payload)
                _launchctl_reload(path, info.name)
                changes.append(ScheduleChange(schedule.id, "updated" if existed else "created"))
            elif path.exists():
                _launchctl_remove(path, info.name)
                changes.append(ScheduleChange(schedule.id, "removed"))
            else:
                changes.append(ScheduleChange(schedule.id, "disabled"))
        except (OSError, WorkspaceError) as error:
            changes.append(ScheduleChange(schedule.id, "failed", False, str(error)))
    for schedule_id in sorted(set(current) - desired_ids):
        path = current[schedule_id]
        try:
            _launchctl_remove(path, path.stem)
            changes.append(ScheduleChange(schedule_id, "removed"))
        except (OSError, WorkspaceError) as error:
            changes.append(ScheduleChange(schedule_id, "failed", False, str(error)))
    return tuple(changes)


def _windows_managed(config_path: Path) -> dict[str, str]:
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise WorkspaceError(result.stderr.strip() or result.stdout.strip())
    prefix = f"OPMLark - {config_path.parent.name} - {_workspace_digest(config_path)} - "
    managed: dict[str, str] = {}
    for row in csv.reader(StringIO(result.stdout)):
        if not row:
            continue
        name = row[0].lstrip("\\")
        if name.startswith(prefix):
            managed[name[len(prefix) :]] = name
    return managed


def _launchd_managed(config_path: Path) -> dict[str, Path]:
    prefix = f"io.opmlark.{_workspace_digest(config_path)}."
    return {
        path.stem[len(prefix) :]: path
        for path in _launchd_directory().glob(f"{prefix}*.plist")
    }


def _cron_entries(config_path: Path, contents: str) -> dict[str, str]:
    prefix = re.escape(f"# opmlark:{_workspace_digest(config_path)}:")
    pattern = re.compile(prefix + r"([a-z0-9][a-z0-9-]*)\s*$")
    return {
        match.group(1): line
        for line in contents.splitlines()
        if (match := pattern.search(line))
    }


def _is_workspace_cron_line(config_path: Path, line: str) -> bool:
    return f"# opmlark:{_workspace_digest(config_path)}:" in line


def _cron_marker(config_path: Path, schedule_id: str = "default") -> str:
    return f"# opmlark:{_workspace_digest(config_path)}:{schedule_id}"


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


def _run_checked(arguments: list[str]) -> None:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode:
        raise WorkspaceError(result.stderr.strip() or result.stdout.strip())


def _launchctl_reload(path: Path, label: str) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    _run_checked(["launchctl", "bootstrap", domain, str(path)])


def _launchctl_remove(path: Path, label: str) -> None:
    domain = f"gui/{os.getuid()}"
    result = subprocess.run(
        ["launchctl", "bootout", f"{domain}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode and path.exists():
        detail = result.stderr.strip() or result.stdout.strip()
        if detail and "No such process" not in detail:
            raise WorkspaceError(detail)
    path.unlink(missing_ok=True)


def _atomic_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temporary:
            temporary.write(contents)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _describe(schedule: Schedule) -> str:
    if schedule.frequency == "weekly":
        return f"weekly on {','.join(schedule.days)} at {schedule.at}"
    if schedule.frequency == "monthly":
        return f"monthly on day {schedule.day} at {schedule.at}"
    if schedule.frequency == "once":
        return f"once on {schedule.date} at {schedule.at}"
    return f"daily at {schedule.at}"


def _time_parts(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, TypeError) as error:
        raise WorkspaceError("Schedule time must use HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise WorkspaceError("Schedule time must use a valid 24-hour HH:MM value")
    return hour, minute


def _workspace_digest(config_path: Path) -> str:
    return hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:12]


def _launchd_directory() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _lines(lines: list[str]) -> str:
    contents = "\n".join(line for line in lines if line.strip()).strip()
    return contents + ("\n" if contents else "")


def _quote(value: str) -> str:
    if _platform() == "windows":
        return f'"{value}"' if " " in value else value
    return shlex.quote(value)


def _is_temporary_npx_path(value: str) -> bool:
    normalized = value.replace("\\", "/").casefold()
    return "/_npx/" in normalized or "/npm-cache/_npx/" in normalized


def _platform() -> str:
    if _is_windows():
        return "windows"
    return "launchd" if sys.platform == "darwin" else "cron"


def _is_windows() -> bool:
    return os.name == "nt"
