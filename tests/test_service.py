from __future__ import annotations

import contextlib
import importlib.util
from datetime import datetime, timezone
from email.utils import format_datetime
from io import StringIO
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from article_importer.configuration import ConfigurationError, ImporterConfig
from article_importer.defuddle import DefuddledArticle
from article_importer.models import FeedSubscription
from article_importer.service import ImportService, RunSummary
from tests.fixtures import RSS, RSS_WITH_NEW_AND_RETRY_ENTRY, RSS_WITH_NEW_ENTRY


GOOD_FEED = FeedSubscription("System Design", "Example", "https://example.test/feed")
BAD_FEED = FeedSubscription("Broken", "Broken", "https://example.test/broken")
ARTICLE = DefuddledArticle("An article", None, "# Unchanged\n")


class ImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.articles = root / "vault" / "Sources" / "Articles"
        self.articles.mkdir(parents=True)
        self.fetcher = Mock(return_value=RSS)
        self.defuddle = Mock(return_value=ARTICLE)
        self.service = self._service([GOOD_FEED])

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _service(
        self,
        subscriptions: list[FeedSubscription],
        *,
        progress: object | None = None,
        logger: logging.Logger | None = None,
    ) -> ImportService:
        config = ImporterConfig(
            vault_path=self.articles.parents[2],
            articles_path=self.articles,
            defuddle_executable="defuddle",
            lookback_days=90,
        )
        return ImportService(
            config,
            subscriptions,
            self.articles.parents[2] / "data" / "articles.sqlite3",
            fetch_bytes=self.fetcher,
            defuddle=self.defuddle,
            progress=progress,
            logger=logger,
        )

    def test_first_run_seeds_without_defuddle(self) -> None:
        summary = self.service.run(dry_run=False)

        self.assertEqual(2, summary.seeded)
        self.assertEqual(0, summary.imported)
        self.defuddle.assert_not_called()

    def test_later_new_entry_is_imported_and_marked(self) -> None:
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_ENTRY)

        summary = self.service.run(dry_run=False)

        self.assertEqual(1, summary.imported)
        note = next(self.articles.rglob("Article - *.md"))
        self.assertEqual(self.articles / "Example", note.parent)
        self.assertIn("ingested_by: opmlark", note.read_text(encoding="utf-8"))

    def test_emits_progress_for_feed_and_imported_article(self) -> None:
        events: list[str] = []
        self.service = self._service([GOOD_FEED], progress=events.append)
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_ENTRY)

        self.service.run(dry_run=False)

        self.assertIn("Starting import: 1 feeds, 90-day lookback", events)
        self.assertIn("[1/1] Fetching Example", events)
        self.assertIn("Defuddling: https://example.test/new", events)
        self.assertIn("Imported: An article", events)

    def test_records_progress_events_in_the_logger(self) -> None:
        log_output = StringIO()
        logger = logging.Logger("test.import-progress", level=logging.INFO)
        logger.addHandler(logging.StreamHandler(log_output))
        self.service = self._service([GOOD_FEED], logger=logger)

        self.service.run(dry_run=False)

        self.assertIn("Starting import: 1 feeds, 90-day lookback", log_output.getvalue())
        self.assertIn("[1/1] Fetching Example", log_output.getvalue())

    def test_bad_feed_does_not_prevent_other_feed(self) -> None:
        self.fetcher.side_effect = lambda url: (
            RSS if url == GOOD_FEED.feed_url else (_ for _ in ()).throw(OSError("offline"))
        )
        self.service = self._service([BAD_FEED, GOOD_FEED])

        summary = self.service.run(dry_run=False)

        self.assertEqual(1, summary.failed_feeds)
        self.assertEqual(2, summary.seeded)

    def test_failed_entry_is_recorded_and_later_retried(self) -> None:
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_ENTRY)
        self.defuddle.side_effect = RuntimeError("Defuddle unavailable")

        failed = self.service.run(dry_run=False)

        self.assertEqual(1, failed.failed_entries)
        self.defuddle.side_effect = None
        retried = self.service.run(dry_run=False)
        self.assertEqual(1, retried.imported)

    def test_dry_run_never_calls_defuddle_or_creates_state(self) -> None:
        summary = self.service.run(dry_run=True)

        self.assertEqual(2, summary.seeded)
        self.defuddle.assert_not_called()
        self.assertFalse((self.articles.parents[2] / "data" / "articles.sqlite3").exists())
        self.assertEqual([], list(self.articles.glob("*.md")))

    def test_dry_run_reports_post_baseline_imports_and_retries_without_writes(self) -> None:
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_ENTRY)
        self.defuddle.side_effect = RuntimeError("Defuddle unavailable")
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_AND_RETRY_ENTRY)
        database = self.articles.parents[2] / "data" / "articles.sqlite3"
        before_database = database.read_bytes()
        calls_before_preview = self.defuddle.call_count

        preview = self.service.run(dry_run=True)

        self.assertEqual(1, preview.would_import)
        self.assertEqual(1, preview.would_retry)
        self.assertEqual(0, preview.imported)
        self.assertEqual(calls_before_preview, self.defuddle.call_count)
        self.assertEqual([], list(self.articles.glob("*.md")))
        self.assertEqual(before_database, database.read_bytes())

    def test_state_failure_after_note_creation_recovers_without_duplicate_note(self) -> None:
        self.service.run(dry_run=False)
        self.fetcher.return_value = _with_recent_entries(RSS_WITH_NEW_ENTRY)

        with patch(
            "article_importer.service.StateStore.mark_imported",
            side_effect=OSError("database is unavailable"),
        ):
            failed = self.service.run(dry_run=False)

        self.assertEqual(1, failed.failed_entries)
        self.assertEqual(1, len(list(self.articles.rglob("Article - *.md"))))
        calls_after_failed_run = self.defuddle.call_count

        recovered = self.service.run(dry_run=False)

        self.assertEqual(0, recovered.failed_entries)
        self.assertEqual(1, len(list(self.articles.rglob("Article - *.md"))))
        self.assertEqual(calls_after_failed_run, self.defuddle.call_count)


if __name__ == "__main__":
    unittest.main()


class FetchArticlesCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.articles = self.root / "vault" / "Sources" / "Articles"
        self.articles.mkdir(parents=True)
        self.config = ImporterConfig(self.articles.parents[2], self.articles, "defuddle")
        self.script = _load_fetch_articles()
        self.script.__file__ = str(self.root / "fetch_articles.py")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_cli_writes_root_relative_utf8_log_and_prints_summary(self) -> None:
        service = Mock()
        service.run.return_value = RunSummary(seeded=2, imported=1)
        output = StringIO()
        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "parse_catalogs", return_value=[]),
            patch.object(self.script, "ImportService", return_value=service),
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main([])

        self.assertEqual(0, exit_code)
        self.assertIn("seeded=2 imported=1 failed_entries=0 failed_feeds=0", output.getvalue())
        self.assertIn(
            "Import summary: seeded=2 imported=1 failed_entries=0 failed_feeds=0",
            (self.root / "data" / "importer.log").read_text(encoding="utf-8"),
        )

    def test_cli_passes_a_flushed_console_progress_reporter(self) -> None:
        service = Mock()
        service.run.return_value = RunSummary()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "parse_catalogs", return_value=[]),
            patch.object(self.script, "ImportService", return_value=service) as constructor,
        ):
            self.script.main([])

        self.assertIs(
            constructor.call_args.kwargs["progress"], self.script._print_progress
        )

    def test_cli_returns_one_for_invalid_configuration(self) -> None:
        output = StringIO()
        with (
            patch.object(
                self.script,
                "load_config",
                side_effect=ConfigurationError("invalid config"),
            ),
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main([])

        self.assertEqual(1, exit_code)
        self.assertIn("invalid config", output.getvalue())

    def test_cli_dry_run_does_not_create_operational_files(self) -> None:
        service = Mock()
        service.run.return_value = RunSummary(seeded=2)

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "parse_catalogs", return_value=[]),
            patch.object(self.script, "ImportService", return_value=service),
        ):
            exit_code = self.script.main(["--dry-run"])

        self.assertEqual(0, exit_code)
        self.assertFalse((self.root / "data").exists())

    def test_cli_add_article_type_migrates_notes_without_importing(self) -> None:
        migration = Mock(return_value=3)
        output = StringIO()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "add_article_type_to_imported_notes", migration),
            patch.object(self.script, "parse_catalogs") as parse_catalogs,
            patch.object(self.script, "ImportService") as service,
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main(["--add-article-type"])

        self.assertEqual(0, exit_code)
        migration.assert_called_once_with(self.articles)
        parse_catalogs.assert_not_called()
        service.assert_not_called()
        self.assertEqual("updated=3\n", output.getvalue())

    def test_cli_rejects_article_type_migration_in_a_dry_run(self) -> None:
        output = StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = self.script.main(["--dry-run", "--add-article-type"])

        self.assertEqual(1, exit_code)
        self.assertIn("cannot be combined", output.getvalue())

    def test_cli_add_topics_migrates_legacy_notes_without_importing(self) -> None:
        migration = Mock(return_value=3)
        output = StringIO()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "add_topics_to_legacy_articles", migration),
            patch.object(self.script, "parse_catalogs") as parse_catalogs,
            patch.object(self.script, "ImportService") as service,
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main(["--add-topics"])

        self.assertEqual(0, exit_code)
        migration.assert_called_once_with(self.articles)
        parse_catalogs.assert_not_called()
        service.assert_not_called()
        self.assertEqual("updated=3\n", output.getvalue())

    def test_cli_groups_articles_by_source_without_importing(self) -> None:
        migration = Mock(return_value=3)
        output = StringIO()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "group_articles_by_source", migration),
            patch.object(self.script, "parse_catalogs") as parse_catalogs,
            patch.object(self.script, "ImportService") as service,
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main(["--group-by-source"])

        self.assertEqual(0, exit_code)
        migration.assert_called_once_with(
            self.articles, self.root / "data" / "articles.sqlite3"
        )
        parse_catalogs.assert_not_called()
        service.assert_not_called()
        self.assertEqual("moved=3\n", output.getvalue())

    def test_cli_validates_catalogs_without_creating_operational_files(self) -> None:
        output = StringIO()
        validation = type("Validation", (), {"checked": 2, "errors": ()})()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "validate_catalogs", return_value=validation) as validate,
            patch.object(self.script, "ImportService") as service,
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main(["--validate-catalogs"])

        self.assertEqual(0, exit_code)
        validate.assert_called_once_with(self.config.feed_catalogs, disabled_sources=self.config.disabled_sources)
        service.assert_not_called()
        self.assertEqual("validated=2 failed=0\n", output.getvalue())
        self.assertFalse((self.root / "data").exists())

    def test_cli_rejects_group_by_source_in_a_dry_run(self) -> None:
        output = StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = self.script.main(["--dry-run", "--group-by-source"])

        self.assertEqual(1, exit_code)
        self.assertIn("cannot be combined", output.getvalue())


def _load_fetch_articles() -> object:
    script_path = Path(__file__).parents[1] / "fetch_articles.py"
    specification = importlib.util.spec_from_file_location("fetch_articles_test", script_path)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not load fetch_articles.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _with_recent_entries(feed: bytes) -> bytes:
    timestamp = format_datetime(datetime.now(timezone.utc)).encode("ascii")
    return feed.replace(b"Wed, 02 Jul 2025 12:00:00 +0000", timestamp).replace(
        b"Thu, 03 Jul 2025 12:00:00 +0000", timestamp
    )
