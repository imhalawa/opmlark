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
            "  [6] List categories\n"
            "  [7] Add category\n"
            "  [8] List failures\n"
            "  [9] Retry failed article\n"
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
            main(["category", "list", "--config", str(config)])
        elif choice == "7":
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
        elif choice == "8":
            main(["failure", "list", "--config", str(config)])
        elif choice == "9":
            url = _prompt("Failed article URL")
            if url:
                main(["failure", "retry", "--url", url, "--config", str(config)])
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
