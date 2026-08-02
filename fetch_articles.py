from __future__ import annotations

import argparse
import logging
from pathlib import Path
import xml.etree.ElementTree as ElementTree

from article_importer.configuration import ConfigurationError, load_config
from article_importer.notes import (
    add_article_type_to_imported_notes,
    add_topics_to_legacy_articles,
    group_articles_by_source,
)
from article_importer.parsing import CatalogError, parse_catalogs, validate_catalogs
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
    parser.add_argument(
        "--add-topics",
        action="store_true",
        help="Add inferred topics to existing non-importer article notes",
    )
    parser.add_argument(
        "--group-by-source",
        action="store_true",
        help="Move root-level article notes into source-named folders",
    )
    parser.add_argument(
        "--validate-catalogs",
        action="store_true",
        help="Verify enabled feed endpoints without importing articles",
    )
    args = parser.parse_args(arguments)
    migrations = args.add_article_type or args.add_topics or args.group_by_source
    if args.dry_run and migrations:
        print("ERROR: --dry-run cannot be combined with a frontmatter migration")
        return 1
    if sum((args.add_article_type, args.add_topics, args.group_by_source)) > 1:
        print("ERROR: frontmatter and article organization migrations cannot be combined")
        return 1
    if args.validate_catalogs and migrations:
        print("ERROR: --validate-catalogs cannot be combined with a migration")
        return 1

    project_root = Path(__file__).resolve().parent
    config_path = (args.config or project_root / "config.toml").resolve()
    data_path = config_path.parent / "data"
    if args.add_article_type:
        try:
            config = load_config(config_path)
            updated = add_article_type_to_imported_notes(config.articles_path)
        except (ConfigurationError, OSError) as error:
            print(f"ERROR: {error}")
            return 1
        print(f"updated={updated}")
        return 0
    if args.add_topics:
        try:
            config = load_config(config_path)
            updated = add_topics_to_legacy_articles(config.articles_path)
        except (ConfigurationError, OSError) as error:
            print(f"ERROR: {error}")
            return 1
        print(f"updated={updated}")
        return 0
    if args.group_by_source:
        try:
            config = load_config(config_path)
            moved = group_articles_by_source(
                config.articles_path, data_path / "articles.sqlite3"
            )
        except (ConfigurationError, OSError) as error:
            print(f"ERROR: {error}")
            return 1
        print(f"moved={moved}")
        return 0
    if args.validate_catalogs:
        try:
            config = load_config(config_path)
            validation = validate_catalogs(
                config.feed_catalogs, disabled_sources=config.disabled_sources
            )
        except (CatalogError, ConfigurationError, OSError, ElementTree.ParseError) as error:
            print(f"ERROR: {error}")
            return 1
        print(f"validated={validation.checked} failed={len(validation.errors)}")
        for error in validation.errors:
            print(f"ERROR: {error}")
        return 1 if validation.errors else 0

    if args.dry_run:
        logger = _dry_run_logger()
    else:
        data_path.mkdir(parents=True, exist_ok=True)
        logger = _configure_logger(data_path / "importer.log")
    try:
        config = load_config(config_path)
        subscriptions = parse_catalogs(
            config.feed_catalogs, disabled_sources=config.disabled_sources
        )
        service = ImportService(
            config,
            subscriptions,
            data_path / "articles.sqlite3",
            logger=logger,
            progress=_print_progress,
        )
        summary = service.run(dry_run=args.dry_run)
    except (CatalogError, ConfigurationError, OSError, ElementTree.ParseError) as error:
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


def _print_progress(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
