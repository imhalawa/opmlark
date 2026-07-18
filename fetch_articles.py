from __future__ import annotations

import argparse
import logging
from pathlib import Path
import xml.etree.ElementTree as ElementTree

from article_importer.configuration import ConfigurationError, load_config
from article_importer.notes import add_article_type_to_imported_notes
from article_importer.parsing import parse_opml
from article_importer.service import ImportService, RunSummary


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import new OPML feed articles with Defuddle.")
    parser.add_argument("--config", type=Path, help="Path to the importer TOML configuration")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview work without writing notes, database state, or operational logs",
    )
    parser.add_argument(
        "--add-article-type",
        action="store_true",
        help="Add type: article to existing importer-created notes",
    )
    args = parser.parse_args(arguments)
    if args.dry_run and args.add_article_type:
        print("ERROR: --dry-run and --add-article-type cannot be combined")
        return 1

    project_root = Path(__file__).resolve().parent
    config_path = args.config or project_root / "config.toml"
    if args.add_article_type:
        try:
            config = load_config(config_path)
            updated = add_article_type_to_imported_notes(config.articles_path)
        except (ConfigurationError, OSError) as error:
            print(f"ERROR: {error}")
            return 1
        print(f"updated={updated}")
        return 0

    data_path = project_root / "data"
    if args.dry_run:
        logger = _dry_run_logger()
    else:
        data_path.mkdir(parents=True, exist_ok=True)
        logger = _configure_logger(data_path / "importer.log")
    try:
        config = load_config(config_path)
        subscriptions = parse_opml(project_root / "feeds.opml")
        service = ImportService(
            config,
            subscriptions,
            data_path / "articles.sqlite3",
            logger=logger,
        )
        summary = service.run(dry_run=args.dry_run)
    except (ConfigurationError, OSError, ElementTree.ParseError) as error:
        logger.error("Article import failed: %s", error)
        print(f"ERROR: {error}")
        return 1
    finally:
        if "summary" not in locals():
            _close_logger(logger)

    message = _summary_message(summary)
    logger.info("Import summary: %s", message)
    print(message)
    _close_logger(logger)
    return 1 if summary.failed_entries or summary.failed_feeds else 0


def _configure_logger(path: Path) -> logging.Logger:
    logger = logging.getLogger("article_importer")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _close_logger(logger)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _dry_run_logger() -> logging.Logger:
    logger = logging.getLogger("article_importer.dry_run")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _close_logger(logger)
    logger.addHandler(logging.NullHandler())
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def _summary_message(summary: RunSummary) -> str:
    return (
        f"seeded={summary.seeded} imported={summary.imported} "
        f"failed_entries={summary.failed_entries} failed_feeds={summary.failed_feeds} "
        f"would_import={summary.would_import} would_retry={summary.would_retry}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
