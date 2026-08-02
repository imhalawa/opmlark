from __future__ import annotations

from pathlib import Path

from article_importer.cli import main
from article_importer.workspace import WorkspaceError, find_config, workspace_status


def run_tui() -> int:
    """Run OPMLark's dependency-free terminal interface."""
    print("\n  OPMLark")
    print("  Give it OPML. Get clean Markdown.\n")
    try:
        config = find_config()
    except WorkspaceError:
        if _prompt("No workspace found. Create one here?", "y").lower() != "y":
            return 0
        if main(["init", str(Path.cwd())]) != 0:
            return 1
        config = find_config()

    while True:
        _print_status(config)
        print(
            "\n  [1] Run ingestion\n"
            "  [2] Preview ingestion\n"
            "  [3] List feeds\n"
            "  [4] Add feed\n"
            "  [5] Remove feed\n"
            "  [6] List catalogs\n"
            "  [7] Add catalog\n"
            "  [8] Disable catalog\n"
            "  [9] List categories\n"
            "  [10] Add category\n"
            "  [11] List articles\n"
            "  [12] Search articles\n"
            "  [13] Read article\n"
            "  [14] List failures\n"
            "  [15] Retry failed article\n"
            "  [16] Manage schedules\n"
            "  [17] Enable catalog\n"
            "  [18] Remove empty category\n"
            "  [19] Rename category\n"
            "  [q] Quit"
        )
        choice = _prompt("Choose", "1").lower()
        if choice == "q":
            return 0
        if choice == "1":
            main(["run", "--config", str(config)])
        elif choice == "2":
            main(["run", "--dry-run", "--config", str(config)])
        elif choice == "3":
            main(["feed", "list", "--config", str(config)])
        elif choice == "4":
            _add_feed(config)
        elif choice == "5":
            source_id = _prompt("Feed id")
            if source_id and _prompt(f"Remove {source_id}?", "n").lower() == "y":
                main(["feed", "remove", "--id", source_id, "--config", str(config)])
        elif choice == "6":
            main(["catalog", "list", "--config", str(config)])
        elif choice == "7":
            catalog_id = _prompt("Catalog id")
            folder = _prompt("Default output folder", catalog_id)
            if catalog_id:
                main(
                    [
                        "catalog",
                        "add",
                        "--id",
                        catalog_id,
                        "--folder",
                        folder,
                        "--config",
                        str(config),
                    ]
                )
        elif choice == "8":
            catalog_id = _prompt("Catalog id")
            if catalog_id and _prompt(f"Disable {catalog_id}?", "n").lower() == "y":
                main(["catalog", "disable", "--id", catalog_id, "--config", str(config)])
        elif choice == "9":
            main(["category", "list", "--config", str(config)])
        elif choice == "10":
            catalog = _prompt("Catalog id", "reading")
            category = _prompt("Category path, for example Engineering/System Design")
            if category:
                main(
                    [
                        "category",
                        "add",
                        "--catalog",
                        catalog,
                        "--name",
                        category,
                        "--config",
                        str(config),
                    ]
                )
        elif choice == "11":
            main(["article", "list", "--limit", "50", "--config", str(config)])
        elif choice == "12":
            query = _prompt("Search text")
            if query:
                main(["article", "search", query, "--config", str(config)])
        elif choice == "13":
            url = _prompt("Article URL")
            if url:
                main(["article", "read", "--url", url, "--config", str(config)])
        elif choice == "14":
            main(["failure", "list", "--config", str(config)])
        elif choice == "15":
            url = _prompt("Failed article URL")
            if url:
                main(["failure", "retry", "--url", url, "--config", str(config)])
        elif choice == "16":
            _schedule_menu(config)
        elif choice == "17":
            catalog_id = _prompt("Catalog id")
            if catalog_id:
                main(["catalog", "enable", "--id", catalog_id, "--config", str(config)])
        elif choice == "18":
            catalog_id = _prompt("Catalog id", "reading")
            category = _prompt("Empty category path")
            if category:
                main(["category", "remove", "--catalog", catalog_id, "--name", category, "--config", str(config)])
        elif choice == "19":
            catalog_id = _prompt("Catalog id", "reading")
            category = _prompt("Category path")
            name = _prompt("New category name")
            if category and name:
                main(
                    [
                        "category",
                        "rename",
                        "--catalog",
                        catalog_id,
                        "--name",
                        category,
                        "--to",
                        name,
                        "--config",
                        str(config),
                    ]
                )
        else:
            print("Unknown choice")


def _add_feed(config: Path) -> None:
    catalog = _prompt("Catalog id", "reading")
    category = _prompt("Category path", "Reading")
    source_id = _prompt("Stable feed id")
    name = _prompt("Feed name")
    url = _prompt("RSS or Atom URL")
    if not all((catalog, category, source_id, name, url)):
        print("Feed was not added: every field is required")
        return
    main(
        [
            "feed",
            "add",
            "--catalog",
            catalog,
            "--category",
            category,
            "--id",
            source_id,
            "--name",
            name,
            "--url",
            url,
            "--config",
            str(config),
        ]
    )


def _schedule_menu(config: Path) -> None:
    while True:
        print(
            "\n  Schedules\n"
            "  [1] List\n"
            "  [2] Add\n"
            "  [3] Edit\n"
            "  [4] Enable\n"
            "  [5] Disable\n"
            "  [6] Remove\n"
            "  [7] Apply\n"
            "  [8] Status\n"
            "  [b] Back"
        )
        choice = _prompt("Choose", "1").lower()
        if choice == "b":
            return
        if choice == "1":
            main(["schedule", "list", "--config", str(config)])
        elif choice in {"2", "3"}:
            schedule_id = _prompt("Schedule id")
            if schedule_id:
                arguments = ["schedule", "add" if choice == "2" else "edit", schedule_id]
                arguments.extend(_schedule_recurrence_prompt())
                main([*arguments, "--config", str(config)])
        elif choice in {"4", "5"}:
            schedule_id = _prompt("Schedule id")
            if schedule_id:
                command = "enable" if choice == "4" else "disable"
                main(["schedule", command, schedule_id, "--config", str(config)])
        elif choice == "6":
            schedule_id = _prompt("Schedule id")
            if schedule_id and _prompt(f"Remove {schedule_id}?", "n").lower() == "y":
                main(["schedule", "remove", schedule_id, "--config", str(config)])
        elif choice == "7":
            main(["schedule", "apply", "--config", str(config)])
        elif choice == "8":
            main(["schedule", "status", "--config", str(config)])
        else:
            print("Unknown choice")


def _schedule_recurrence_prompt() -> list[str]:
    frequency = _prompt("Frequency (daily, weekly, monthly, once)", "daily").lower()
    if frequency == "weekly":
        recurrence = ["--weekly", _prompt("Weekdays, comma-separated", "mon")]
    elif frequency == "monthly":
        recurrence = ["--monthly", _prompt("Day of month", "1")]
    elif frequency == "once":
        recurrence = ["--once", _prompt("Date (YYYY-MM-DD)")]
    else:
        recurrence = ["--daily"]
    return [*recurrence, "--at", _prompt("Local time (HH:MM)", "07:00")]


def _print_status(config: Path) -> None:
    status = workspace_status(config)
    articles = status["articles"]
    print(
        f"\n  {status['feeds']} feeds | {articles['imported']} imported | "
        f"{articles['failed']} need attention"
    )


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"  {label}{suffix}: ").strip()
    return value or default
