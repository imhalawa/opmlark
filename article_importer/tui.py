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
            "  [16] Show schedule\n"
            "  [17] Install schedule\n"
            "  [18] Remove schedule\n"
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
            main(["schedule", "show", "--config", str(config)])
        elif choice == "17":
            time = _prompt("Daily time (HH:MM)", "07:00")
            main(["schedule", "install", "--time", time, "--config", str(config)])
        elif choice == "18":
            if _prompt("Remove this workspace schedule?", "n").lower() == "y":
                main(["schedule", "remove", "--config", str(config)])
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
