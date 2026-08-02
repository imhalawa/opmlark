from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import re
import tomllib

from article_importer.configuration import Schedule, load_config
from article_importer.workspace import WorkspaceError


def list_schedule_config(config_path: Path) -> tuple[Schedule, ...]:
    return load_config(config_path).schedules


def add_schedule_config(config_path: Path, schedule: Schedule) -> Schedule:
    _validate_schedule(schedule)
    if any(item.id == schedule.id for item in list_schedule_config(config_path)):
        raise WorkspaceError(f"Schedule id already exists: {schedule.id}")
    contents = config_path.read_text(encoding="utf-8").rstrip()
    _replace_validated(config_path, contents + "\n\n" + _serialize(schedule))
    return schedule


def edit_schedule_config(
    config_path: Path, schedule_id: str, replacement: Schedule
) -> Schedule:
    if replacement.id != schedule_id:
        raise WorkspaceError("Editing a schedule cannot rename its id")
    _validate_schedule(replacement)
    contents = config_path.read_text(encoding="utf-8")
    block = _find_block(contents, schedule_id)
    if block is None:
        raise WorkspaceError(f"Unknown schedule: {schedule_id}")
    start, end = block
    updated = contents[:start] + _serialize(replacement) + contents[end:]
    _replace_validated(config_path, updated.rstrip() + "\n")
    return replacement


def set_schedule_enabled(config_path: Path, schedule_id: str, enabled: bool) -> Schedule:
    current = _schedule(config_path, schedule_id)
    replacement = Schedule(
        current.id,
        current.frequency,
        current.at,
        enabled,
        current.days,
        current.day,
        current.date,
    )
    return edit_schedule_config(config_path, schedule_id, replacement)


def remove_schedule_config(config_path: Path, schedule_id: str) -> Schedule:
    current = _schedule(config_path, schedule_id)
    contents = config_path.read_text(encoding="utf-8")
    block = _find_block(contents, schedule_id)
    if block is None:
        raise WorkspaceError(f"Unknown schedule: {schedule_id}")
    start, end = block
    updated = (contents[:start].rstrip() + "\n\n" + contents[end:].lstrip()).rstrip() + "\n"
    _replace_validated(config_path, updated)
    return current


def _schedule(config_path: Path, schedule_id: str) -> Schedule:
    match = next(
        (item for item in list_schedule_config(config_path) if item.id == schedule_id),
        None,
    )
    if match is None:
        raise WorkspaceError(f"Unknown schedule: {schedule_id}")
    return match


def _validate_schedule(schedule: Schedule) -> None:
    with NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as temporary:
        temporary.write(
            '[importer]\noutput_path = "."\nlookback_days = 90\n\n' + _serialize(schedule)
        )
        path = Path(temporary.name)
    try:
        load_config(path)
    except Exception as error:
        raise WorkspaceError(str(error)) from error
    finally:
        path.unlink(missing_ok=True)


def _serialize(schedule: Schedule) -> str:
    lines = [
        "[[schedules]]",
        f"id = {json.dumps(schedule.id)}",
        f"frequency = {json.dumps(schedule.frequency)}",
    ]
    if schedule.frequency == "weekly":
        lines.append("days = [" + ", ".join(json.dumps(day) for day in schedule.days) + "]")
    elif schedule.frequency == "monthly":
        lines.append(f"day = {schedule.day}")
    elif schedule.frequency == "once":
        lines.append(f"date = {json.dumps(schedule.date)}")
    lines.append(f"at = {json.dumps(schedule.at)}")
    if not schedule.enabled:
        lines.append("enabled = false")
    return "\n".join(lines) + "\n"


def _find_block(contents: str, schedule_id: str) -> tuple[int, int] | None:
    headers = list(re.finditer(r"(?m)^\s*\[\[schedules\]\]\s*$", contents))
    for header in headers:
        next_header = re.search(r"(?m)^\s*\[", contents[header.end() :])
        end = header.end() + next_header.start() if next_header else len(contents)
        block = contents[header.start() : end]
        try:
            block_id = tomllib.loads(block)["schedules"][0]["id"]
        except (KeyError, IndexError, TypeError, tomllib.TOMLDecodeError):
            continue
        if block_id == schedule_id:
            return header.start(), end
    return None


def _replace_validated(config_path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=config_path.parent, delete=False
        ) as temporary:
            temporary.write(contents)
            temporary_path = Path(temporary.name)
        load_config(temporary_path)
        temporary_path.replace(config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
