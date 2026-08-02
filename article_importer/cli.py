from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ElementTree

from article_importer import __version__
from article_importer.configuration import ConfigurationError, Schedule, load_config
from article_importer.library import LibraryError, list_articles, read_article, search_articles
from article_importer.parsing import CatalogError, parse_catalogs
from article_importer.run_lock import RunLock
from article_importer.service import ImportService
from article_importer.schedule_config import (
    add_schedule_config,
    edit_schedule_config,
    list_schedule_config,
    remove_schedule_config,
    set_schedule_enabled,
)
from article_importer.scheduling import (
    apply_schedules,
    install_schedule,
    remove_native_schedule,
    schedule_info,
    schedule_status,
)
from article_importer.workspace import (
    WorkspaceError,
    add_category,
    add_catalog,
    add_feed,
    find_config,
    initialize_workspace,
    list_catalogs,
    list_categories,
    list_feeds,
    list_failures,
    disable_catalog,
    enable_catalog,
    remove_category,
    rename_category,
    remove_feed,
    retry_failure,
    to_json,
    workspace_status,
)


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(arguments)
    if args.command is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from article_importer.tui import run_tui

            return run_tui()
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except (
        CatalogError,
        ConfigurationError,
        WorkspaceError,
        LibraryError,
        ElementTree.ParseError,
        sqlite3.Error,
        OSError,
        ValueError,
    ) as error:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opmlark",
        description="Watch OPML feeds and preserve new articles as clean Markdown.",
    )
    parser.add_argument("--version", action="version", version=f"OPMLark {__version__}")
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser("init", help="Create a portable OPMLark workspace")
    init.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    init.add_argument("--output", default="articles", help="Workspace-relative article directory")
    _json_flag(init)
    init.set_defaults(handler=_init)

    run = commands.add_parser("run", help="Fetch feeds and ingest eligible articles")
    _config_flag(run)
    run.add_argument("--dry-run", action="store_true")
    _json_flag(run)
    run.set_defaults(handler=_run)

    status = commands.add_parser("status", help="Show workspace and ingestion state")
    _config_flag(status)
    _json_flag(status)
    status.set_defaults(handler=_status)

    doctor = commands.add_parser("doctor", help="Check workspace prerequisites")
    _config_flag(doctor)
    _json_flag(doctor)
    doctor.set_defaults(handler=_doctor)

    schedule = commands.add_parser("schedule", help="Manage token-free background ingestion")
    schedule_commands = schedule.add_subparsers(dest="schedule_command", required=True)
    schedule_list = schedule_commands.add_parser("list")
    _config_flag(schedule_list)
    _json_flag(schedule_list)
    schedule_list.set_defaults(handler=_schedule_list)
    schedule_add = schedule_commands.add_parser("add")
    schedule_add.add_argument("id")
    _schedule_recurrence_flags(schedule_add)
    _config_flag(schedule_add)
    _json_flag(schedule_add)
    schedule_add.set_defaults(handler=_schedule_add)
    schedule_edit = schedule_commands.add_parser("edit")
    schedule_edit.add_argument("id")
    _schedule_recurrence_flags(schedule_edit)
    _config_flag(schedule_edit)
    _json_flag(schedule_edit)
    schedule_edit.set_defaults(handler=_schedule_edit)
    for name, handler in (("enable", _schedule_enable), ("disable", _schedule_disable)):
        command = schedule_commands.add_parser(name)
        command.add_argument("id")
        _config_flag(command)
        _json_flag(command)
        command.set_defaults(handler=handler)
    schedule_remove = schedule_commands.add_parser("remove")
    schedule_remove.add_argument("id", nargs="?", default="default")
    _config_flag(schedule_remove)
    _json_flag(schedule_remove)
    schedule_remove.set_defaults(handler=_schedule_remove)
    for name, handler in (("apply", _schedule_apply), ("status", _schedule_status)):
        command = schedule_commands.add_parser(name)
        _config_flag(command)
        _json_flag(command)
        command.set_defaults(handler=handler)
    schedule_show = schedule_commands.add_parser("show")
    schedule_show.add_argument("--time", default="07:00")
    _config_flag(schedule_show)
    _json_flag(schedule_show)
    schedule_show.set_defaults(handler=_schedule_show)
    schedule_install = schedule_commands.add_parser("install")
    schedule_install.add_argument("--time", default="07:00")
    _config_flag(schedule_install)
    _json_flag(schedule_install)
    schedule_install.set_defaults(handler=_schedule_install)

    catalog = commands.add_parser("catalog", help="Manage OPML catalogs")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_commands.add_parser("list")
    _config_flag(catalog_list)
    _json_flag(catalog_list)
    catalog_list.set_defaults(handler=_catalog_list)
    catalog_add = catalog_commands.add_parser("add")
    _config_flag(catalog_add)
    catalog_add.add_argument("--id", required=True)
    catalog_add.add_argument("--path")
    catalog_add.add_argument("--folder")
    _json_flag(catalog_add)
    catalog_add.set_defaults(handler=_catalog_add)
    catalog_disable = catalog_commands.add_parser("disable")
    _config_flag(catalog_disable)
    catalog_disable.add_argument("--id", required=True)
    _json_flag(catalog_disable)
    catalog_disable.set_defaults(handler=_catalog_disable)
    catalog_enable = catalog_commands.add_parser("enable")
    _config_flag(catalog_enable)
    catalog_enable.add_argument("--id", required=True)
    _json_flag(catalog_enable)
    catalog_enable.set_defaults(handler=_catalog_enable)

    category = commands.add_parser("category", help="Manage OPML categories")
    category_commands = category.add_subparsers(dest="category_command", required=True)
    category_list = category_commands.add_parser("list")
    _config_flag(category_list)
    category_list.add_argument("--catalog")
    _json_flag(category_list)
    category_list.set_defaults(handler=_category_list)
    category_add = category_commands.add_parser("add")
    _config_flag(category_add)
    category_add.add_argument("--catalog", required=True)
    category_add.add_argument("--name", required=True)
    _json_flag(category_add)
    category_add.set_defaults(handler=_category_add)
    category_remove = category_commands.add_parser("remove")
    _config_flag(category_remove)
    category_remove.add_argument("--catalog", required=True)
    category_remove.add_argument("--name", required=True)
    _json_flag(category_remove)
    category_remove.set_defaults(handler=_category_remove)
    category_rename = category_commands.add_parser("rename")
    _config_flag(category_rename)
    category_rename.add_argument("--catalog", required=True)
    category_rename.add_argument("--name", required=True)
    category_rename.add_argument("--to", required=True)
    _json_flag(category_rename)
    category_rename.set_defaults(handler=_category_rename)

    feed = commands.add_parser("feed", help="Manage feed subscriptions")
    feed_commands = feed.add_subparsers(dest="feed_command", required=True)
    feed_list = feed_commands.add_parser("list")
    _config_flag(feed_list)
    _json_flag(feed_list)
    feed_list.set_defaults(handler=_feed_list)
    feed_add = feed_commands.add_parser("add")
    _config_flag(feed_add)
    feed_add.add_argument("--catalog", required=True)
    feed_add.add_argument("--id", required=True)
    feed_add.add_argument("--name", required=True)
    feed_add.add_argument("--url", required=True)
    feed_add.add_argument("--category", required=True)
    feed_add.add_argument("--home-url")
    feed_add.add_argument("--folder")
    _json_flag(feed_add)
    feed_add.set_defaults(handler=_feed_add)
    feed_remove = feed_commands.add_parser("remove")
    _config_flag(feed_remove)
    feed_remove.add_argument("--id", required=True)
    _json_flag(feed_remove)
    feed_remove.set_defaults(handler=_feed_remove)

    failure = commands.add_parser("failure", help="Inspect and retry failed articles")
    failure_commands = failure.add_subparsers(dest="failure_command", required=True)
    failure_list = failure_commands.add_parser("list")
    _config_flag(failure_list)
    _json_flag(failure_list)
    failure_list.set_defaults(handler=_failure_list)
    failure_retry = failure_commands.add_parser("retry")
    _config_flag(failure_retry)
    failure_retry.add_argument("--url", required=True)
    _json_flag(failure_retry)
    failure_retry.set_defaults(handler=_failure_retry)

    article = commands.add_parser("article", help="Query and read collected articles")
    article_commands = article.add_subparsers(dest="article_command", required=True)
    article_list = article_commands.add_parser("list")
    _config_flag(article_list)
    article_list.add_argument("--feed")
    article_list.add_argument("--since", help="Minimum ISO-8601 publication timestamp")
    article_list.add_argument("--limit", type=int, default=100)
    _json_flag(article_list)
    article_list.set_defaults(handler=_article_list)
    article_search = article_commands.add_parser("search")
    _config_flag(article_search)
    article_search.add_argument("query")
    article_search.add_argument("--limit", type=int, default=20)
    _json_flag(article_search)
    article_search.set_defaults(handler=_article_search)
    article_read = article_commands.add_parser("read")
    _config_flag(article_read)
    article_read.add_argument("--url", required=True)
    _json_flag(article_read)
    article_read.set_defaults(handler=_article_read)
    return parser


def _config_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Path to config.toml")


def _json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def _schedule_recurrence_flags(parser: argparse.ArgumentParser) -> None:
    recurrence = parser.add_mutually_exclusive_group()
    recurrence.add_argument("--daily", action="store_true")
    recurrence.add_argument("--weekly", metavar="DAYS", help="Comma-separated weekdays")
    recurrence.add_argument("--monthly", type=int, metavar="DAY")
    recurrence.add_argument("--once", metavar="YYYY-MM-DD")
    parser.add_argument("--at", metavar="HH:MM")


def _init(args: argparse.Namespace) -> int:
    result = initialize_workspace(args.path, args.output)
    _emit(result, args.json, lambda value: f"Created OPMLark workspace at {value['workspace']}")
    return 0


def _run(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    if args.dry_run:
        return _execute_run(args, config_path)
    with RunLock(config_path.parent / "data" / "import.lock") as lock:
        if not lock.acquired:
            result = {"ok": True, "skipped": "already_running"}
            _emit(result, args.json, lambda value: "Another ingestion run is active; skipped")
            return 0
        return _execute_run(args, config_path)


def _execute_run(args: argparse.Namespace, config_path: Path) -> int:
    config = load_config(config_path)
    subscriptions = parse_catalogs(
        config.feed_catalogs, disabled_sources=config.disabled_sources
    )
    data_path = config_path.parent / "data"
    logger = _logger(None if args.dry_run else data_path / "importer.log")
    progress = None if args.json else lambda message: print(message, flush=True)
    try:
        summary = ImportService(
            config,
            subscriptions,
            data_path / "articles.sqlite3",
            logger=logger,
            progress=progress,
        ).run(dry_run=args.dry_run)
    finally:
        _close_logger(logger)
    result = asdict(summary)
    result["ok"] = summary.failed_entries == 0 and summary.failed_feeds == 0
    _emit(result, args.json, _summary_text)
    return 0 if result["ok"] else 1


def _status(args: argparse.Namespace) -> int:
    result = workspace_status(find_config(args.config))
    _emit(
        result,
        args.json,
        lambda value: (
            f"catalogs={value['catalogs']} feeds={value['feeds']} "
            + " ".join(f"{key}={count}" for key, count in value["articles"].items())
        ),
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    config = load_config(config_path)
    checks = {
        "python": sys.version.split()[0],
        "defuddle": shutil.which(config.defuddle_executable) or config.defuddle_executable,
        "config": str(config_path),
        "output": str(config.articles_path),
        "catalogs": len(config.feed_catalogs),
    }
    checks["ok"] = bool(shutil.which(config.defuddle_executable) or Path(config.defuddle_executable).is_file())
    _emit(checks, args.json, lambda value: "\n".join(f"{key}: {item}" for key, item in value.items()))
    return 0 if checks["ok"] else 1


def _schedule_show(args: argparse.Namespace) -> int:
    item = schedule_info(find_config(args.config), args.time)
    _emit(item, args.json, lambda value: f"{value.name}\n{value.time}  {value.command}")
    return 0


def _schedule_install(args: argparse.Namespace) -> int:
    item = install_schedule(find_config(args.config), args.time)
    _emit(item, args.json, lambda value: f"Installed {value.name} at {value.time}")
    return 0


def _schedule_list(args: argparse.Namespace) -> int:
    items = list_schedule_config(find_config(args.config))
    _emit(
        items,
        args.json,
        lambda values: _table(values, ("id", "frequency", "at", "enabled")),
    )
    return 0


def _schedule_add(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    item = add_schedule_config(config_path, _schedule_from_args(args))
    return _emit_schedule_mutation(item, apply_schedules(config_path), args.json, "Added")


def _schedule_edit(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    current = _schedule_by_id(config_path, args.id)
    item = edit_schedule_config(
        config_path, args.id, _schedule_from_args(args, current=current)
    )
    return _emit_schedule_mutation(item, apply_schedules(config_path), args.json, "Updated")


def _schedule_enable(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    item = set_schedule_enabled(config_path, args.id, True)
    return _emit_schedule_mutation(item, apply_schedules(config_path), args.json, "Enabled")


def _schedule_disable(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    item = set_schedule_enabled(config_path, args.id, False)
    return _emit_schedule_mutation(item, apply_schedules(config_path), args.json, "Disabled")


def _schedule_remove(args: argparse.Namespace) -> int:
    config_path = find_config(args.config)
    native = remove_native_schedule(config_path, args.id)
    if not native.ok:
        raise WorkspaceError(native.detail)
    item = remove_schedule_config(config_path, args.id)
    result = {"ok": True, "schedule": asdict(item), "native": asdict(native)}
    _emit(result, args.json, lambda value: f"Removed schedule {item.id}")
    return 0


def _schedule_apply(args: argparse.Namespace) -> int:
    changes = apply_schedules(find_config(args.config))
    _emit(changes, args.json, lambda values: _table(values, ("id", "action", "ok", "detail")))
    return 0 if all(item.ok for item in changes) else 1


def _schedule_status(args: argparse.Namespace) -> int:
    items = schedule_status(find_config(args.config))
    _emit(items, args.json, lambda values: _table(values, ("id", "action", "ok", "detail")))
    return 0 if all(item.ok for item in items) else 1


def _schedule_from_args(
    args: argparse.Namespace, *, current: Schedule | None = None
) -> Schedule:
    frequency: str | None = None
    days: tuple[str, ...] = ()
    day: int | None = None
    date_value: str | None = None
    if args.daily:
        frequency = "daily"
    elif args.weekly is not None:
        frequency = "weekly"
        days = tuple(item.strip().casefold() for item in args.weekly.split(",") if item.strip())
    elif args.monthly is not None:
        frequency = "monthly"
        day = args.monthly
    elif args.once is not None:
        frequency = "once"
        date_value = args.once
    elif current is not None:
        frequency = current.frequency
        days, day, date_value = current.days, current.day, current.date
    elif sys.stdin.isatty() and sys.stdout.isatty():
        frequency = input("Frequency (daily, weekly, monthly, once) [daily]: ").strip().casefold() or "daily"
        if frequency == "weekly":
            days = tuple(item.strip().casefold() for item in input("Weekdays (comma-separated): ").split(",") if item.strip())
        elif frequency == "monthly":
            day = int(input("Day of month: ").strip())
        elif frequency == "once":
            date_value = input("Date (YYYY-MM-DD): ").strip()
    else:
        raise WorkspaceError("Choose one recurrence: --daily, --weekly, --monthly, or --once")
    at = args.at or (current.at if current is not None else "07:00")
    enabled = current.enabled if current is not None else True
    return Schedule(args.id, frequency, at, enabled, days, day, date_value)


def _schedule_by_id(config_path: Path, schedule_id: str) -> Schedule:
    item = next(
        (value for value in list_schedule_config(config_path) if value.id == schedule_id),
        None,
    )
    if item is None:
        raise WorkspaceError(f"Unknown schedule: {schedule_id}")
    return item


def _emit_schedule_mutation(
    schedule: Schedule, changes: tuple[object, ...], as_json: bool, verb: str
) -> int:
    ok = all(getattr(item, "ok", False) for item in changes)
    result = {
        "ok": ok,
        "schedule": asdict(schedule),
        "changes": [asdict(item) for item in changes],
    }
    _emit(
        result,
        as_json,
        lambda value: f"{verb} schedule {schedule.id}; "
        + ", ".join(f"{item.id}={item.action}" for item in changes),
    )
    return 0 if ok else 1


def _catalog_list(args: argparse.Namespace) -> int:
    items = list_catalogs(find_config(args.config))
    _emit(items, args.json, lambda values: _table(values, ("id", "path", "folder", "enabled")))
    return 0


def _catalog_add(args: argparse.Namespace) -> int:
    item = add_catalog(
        find_config(args.config),
        catalog_id=args.id,
        path_value=args.path,
        folder=args.folder,
    )
    _emit(item, args.json, lambda value: f"Added catalog {value.id}: {value.path}")
    return 0


def _catalog_disable(args: argparse.Namespace) -> int:
    item = disable_catalog(find_config(args.config), args.id)
    _emit(item, args.json, lambda value: f"Disabled catalog {value.id}")
    return 0


def _catalog_enable(args: argparse.Namespace) -> int:
    item = enable_catalog(find_config(args.config), args.id)
    _emit(item, args.json, lambda value: f"Enabled catalog {value.id}")
    return 0


def _category_list(args: argparse.Namespace) -> int:
    items = list_categories(find_config(args.config), args.catalog)
    _emit(items, args.json, lambda values: _mapping_table(values, ("catalog", "category")))
    return 0


def _category_add(args: argparse.Namespace) -> int:
    item = add_category(find_config(args.config), args.catalog, args.name)
    _emit(item, args.json, lambda value: f"Added {value['category']} to {value['catalog']}")
    return 0


def _category_remove(args: argparse.Namespace) -> int:
    item = remove_category(find_config(args.config), args.catalog, args.name)
    _emit(item, args.json, lambda value: f"Removed empty category {value['category']}")
    return 0


def _category_rename(args: argparse.Namespace) -> int:
    item = rename_category(find_config(args.config), args.catalog, args.name, args.to)
    _emit(
        item,
        args.json,
        lambda value: f"Renamed {value['category']} to {value['name']}",
    )
    return 0


def _feed_list(args: argparse.Namespace) -> int:
    items = list_feeds(find_config(args.config))
    _emit(items, args.json, lambda values: _table(values, ("id", "name", "category", "catalog", "url")))
    return 0


def _feed_add(args: argparse.Namespace) -> int:
    item = add_feed(
        find_config(args.config),
        catalog_id=args.catalog,
        feed_id=args.id,
        name=args.name,
        url=args.url,
        category=args.category,
        home_url=args.home_url,
        folder=args.folder,
    )
    _emit(item, args.json, lambda value: f"Added feed {value.name} ({value.id})")
    return 0


def _feed_remove(args: argparse.Namespace) -> int:
    item = remove_feed(find_config(args.config), args.id)
    _emit(item, args.json, lambda value: f"Removed feed {value.name} ({value.id})")
    return 0


def _failure_list(args: argparse.Namespace) -> int:
    items = list_failures(find_config(args.config))
    _emit(
        items,
        args.json,
        lambda values: _mapping_table(values, ("attempts", "updated", "url", "error")),
    )
    return 0


def _failure_retry(args: argparse.Namespace) -> int:
    item = retry_failure(find_config(args.config), args.url)
    _emit(item, args.json, lambda value: f"Queued retry for {value['url']}")
    return 0


def _state_path(args: argparse.Namespace) -> Path:
    return find_config(args.config).parent / "data" / "articles.sqlite3"


def _article_list(args: argparse.Namespace) -> int:
    items = list_articles(
        _state_path(args), feed=args.feed, since=args.since, limit=args.limit
    )
    _emit(items, args.json, lambda values: _table(values, ("published", "feed", "title", "url", "path")))
    return 0


def _article_search(args: argparse.Namespace) -> int:
    items = search_articles(_state_path(args), args.query, limit=args.limit)
    _emit(items, args.json, lambda values: _mapping_table(values, ("feed", "title", "url", "path", "excerpt")))
    return 0


def _article_read(args: argparse.Namespace) -> int:
    item = read_article(_state_path(args), args.url)
    print(to_json(item) if args.json else item["markdown"], end="\n" if args.json else "")
    return 0


def _emit(value: object, as_json: bool, render: object) -> None:
    print(to_json(value) if as_json else render(value))


def _summary_text(value: dict[str, object]) -> str:
    return " ".join(f"{key}={item}" for key, item in value.items() if key != "ok")


def _table(values: tuple[object, ...], fields: tuple[str, ...]) -> str:
    rows = [[str(getattr(value, field, "") or "") for field in fields] for value in values]
    return _render_rows(fields, rows)


def _mapping_table(values: tuple[dict[str, object], ...], fields: tuple[str, ...]) -> str:
    return _render_rows(
        fields,
        [[str(value.get(field, "") or "") for field in fields] for value in values],
    )


def _render_rows(headers: tuple[str, ...], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]
    lines = ["  ".join(header.ljust(width) for header, width in zip(headers, widths))]
    lines.extend("  ".join(cell.ljust(width) for cell, width in zip(row, widths)) for row in rows)
    return "\n".join(lines)


def _logger(path: Path | None) -> logging.Logger:
    logger = logging.getLogger(f"opmlark.{datetime.now(timezone.utc).timestamp()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if path is None:
        logger.addHandler(logging.NullHandler())
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
