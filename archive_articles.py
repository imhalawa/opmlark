from __future__ import annotations

import argparse
import logging
from pathlib import Path

from article_importer.archive import ARCHIVE_SOURCES, ArchiveImportService, ArchiveRunSummary
from article_importer.configuration import ConfigurationError, load_config


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover and import historic blog articles with Defuddle."
    )
    parser.add_argument("--config", type=Path, help="Path to the importer TOML configuration")
    parser.add_argument(
        "--source",
        choices=("all", *ARCHIVE_SOURCES),
        default="all",
        help="Archive source to import (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=_positive_limit,
        help="Maximum pending articles to process; omit to process every discovered URL",
    )
    args = parser.parse_args(arguments)

    project_root = Path(__file__).resolve().parent
    data_path = project_root / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    logger = _configure_logger(data_path / "archive-importer.log")
    try:
        config = load_config(args.config or project_root / "config.toml")
        service = ArchiveImportService(
            config,
            data_path / "articles.sqlite3",
            logger=logger,
        )
        summary = service.run(source=args.source, limit=args.limit)
    except (ConfigurationError, OSError) as error:
        logger.error("Archive import failed: %s", error)
        print(f"ERROR: {error}")
        return 1
    finally:
        if "summary" not in locals():
            _close_logger(logger)

    message = _summary_message(summary)
    logger.info("Archive import summary: %s", message)
    print(message)
    _close_logger(logger)
    return 1 if summary.failed or summary.failed_sources else 0


def _positive_limit(value: str) -> int:
    limit = int(value)
    if limit <= 0:
        raise argparse.ArgumentTypeError("--limit must be a positive integer")
    return limit


def _configure_logger(path: Path) -> logging.Logger:
    logger = logging.getLogger("article_importer.archive")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _close_logger(logger)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def _summary_message(summary: ArchiveRunSummary) -> str:
    return (
        f"discovered={summary.discovered} pending={summary.pending} "
        f"imported={summary.imported} recovered={summary.recovered} "
        f"failed={summary.failed} failed_sources={summary.failed_sources}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
