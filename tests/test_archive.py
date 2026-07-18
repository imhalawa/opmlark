from __future__ import annotations

from datetime import datetime, timezone
import contextlib
import importlib.util
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from article_importer.archive import (
    ARCHIVE_SOURCES,
    ArchiveImportService,
    discover_bytebytego_urls,
    discover_highscalability_urls,
    discover_martin_kleppmann_urls,
)
from article_importer.configuration import ImporterConfig
from article_importer.defuddle import DefuddledArticle
from article_importer.parsing import parse_opml


BYTEBYTEGO_SITEMAP = b"""
<html><body>
  <a href="/p/first-article">First</a>
  <a href="https://blog.bytebytego.com/p/second-article">Second</a>
  <a href="/about">About</a>
  <a href="/p/first-article">Duplicate</a>
</body></html>
"""

HIGHSCALABILITY_SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://highscalability.com/blog/first</loc></url>
  <url><loc>https://highscalability.com/blog/second</loc></url>
  <url><loc>https://highscalability.com/blog/first</loc></url>
</urlset>
"""

MARTIN_ARCHIVE = b"""
<ul>
  <li>03 Jan 2024: <a href="/2024/first.html">First</a></li>
  <li>02 May 2023: <a href="https://martin.kleppmann.com/2023/second.html">Second</a></li>
  <li><a href="/about.html">About</a></li>
</ul>
"""


class ArchiveDiscoveryTests(unittest.TestCase):
    def test_bytebytego_yearly_sitemaps_return_unique_article_urls(self) -> None:
        requested: list[str] = []

        def fetch(url: str) -> bytes:
            requested.append(url)
            return BYTEBYTEGO_SITEMAP

        urls = discover_bytebytego_urls(fetch, years=range(2021, 2023))

        self.assertEqual(
            (
                "https://blog.bytebytego.com/p/first-article",
                "https://blog.bytebytego.com/p/second-article",
            ),
            urls,
        )
        self.assertEqual(
            [
                "https://blog.bytebytego.com/sitemap/2021",
                "https://blog.bytebytego.com/sitemap/2022",
            ],
            requested,
        )

    def test_highscalability_sitemap_returns_unique_urls(self) -> None:
        self.assertEqual(
            (
                "https://highscalability.com/blog/first",
                "https://highscalability.com/blog/second",
            ),
            discover_highscalability_urls(lambda url: HIGHSCALABILITY_SITEMAP),
        )

    def test_martin_archive_only_returns_dated_post_links(self) -> None:
        self.assertEqual(
            (
                "https://martin.kleppmann.com/2024/first.html",
                "https://martin.kleppmann.com/2023/second.html",
            ),
            discover_martin_kleppmann_urls(lambda url: MARTIN_ARCHIVE),
        )


class ArchiveImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.articles = root / "vault" / "Sources" / "Articles"
        self.articles.mkdir(parents=True)
        self.config = ImporterConfig(self.articles.parents[2], self.articles, "defuddle")
        self.defuddle = Mock(
            return_value=DefuddledArticle("Imported", None, "# Unchanged\n")
        )
        self.discover = {
            "bytebytego": lambda fetch: (
                "https://blog.bytebytego.com/p/first",
                "https://blog.bytebytego.com/p/second",
            ),
            "highscalability": lambda fetch: ("https://highscalability.com/blog/only",),
            "martin-kleppmann": lambda fetch: ("https://martin.kleppmann.com/2024/only.html",),
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _service(self) -> ArchiveImportService:
        return ArchiveImportService(
            self.config,
            self.articles.parents[2] / "data" / "articles.sqlite3",
            fetch_bytes=Mock(),
            discoverers=self.discover,
            defuddle=self.defuddle,
        )

    def test_source_filter_only_discovers_and_imports_the_requested_source(self) -> None:
        summary = self._service().run(source="highscalability")

        self.assertEqual(1, summary.discovered)
        self.assertEqual(1, summary.imported)
        self.assertEqual(
            ["https://highscalability.com/blog/only"],
            [call.args[0] for call in self.defuddle.call_args_list],
        )

    def test_limit_applies_to_pending_urls_so_a_rerun_progresses(self) -> None:
        service = self._service()

        first = service.run(source="bytebytego", limit=1)
        second = service.run(source="bytebytego", limit=1)

        self.assertEqual(1, first.imported)
        self.assertEqual(1, second.imported)
        self.assertEqual(
            [
                "https://blog.bytebytego.com/p/first",
                "https://blog.bytebytego.com/p/second",
            ],
            [call.args[0] for call in self.defuddle.call_args_list],
        )

    def test_existing_legacy_note_source_is_marked_imported_without_defuddle(self) -> None:
        self.discover["bytebytego"] = lambda fetch: ("https://blog.bytebytego.com/p/first",)
        source = "https://blog.bytebytego.com/p/first"
        (self.articles / "legacy.md").write_text(
            "---\nsource: https://blog.bytebytego.com/p/first\n---\nexisting note\n",
            encoding="utf-8",
        )

        summary = self._service().run(source="bytebytego", limit=1)
        rerun = self._service().run(source="bytebytego", limit=1)

        self.assertEqual(1, summary.recovered)
        self.assertEqual(0, summary.imported)
        self.assertEqual(0, rerun.pending)
        self.defuddle.assert_not_called()

    def test_source_text_outside_frontmatter_does_not_suppress_an_import(self) -> None:
        self.discover["bytebytego"] = lambda fetch: ("https://blog.bytebytego.com/p/first",)
        (self.articles / "unrelated.md").write_text(
            "# Notes\n\nsource: https://blog.bytebytego.com/p/first\n",
            encoding="utf-8",
        )

        summary = self._service().run(source="bytebytego")

        self.assertEqual(1, summary.imported)
        self.assertEqual(0, summary.recovered)
        self.defuddle.assert_called_once()

    def test_failed_urls_are_retried_on_the_next_run(self) -> None:
        self.defuddle.side_effect = RuntimeError("Defuddle unavailable")
        service = self._service()

        failed = service.run(source="highscalability")
        self.defuddle.side_effect = None
        retried = service.run(source="highscalability")

        self.assertEqual(1, failed.failed)
        self.assertEqual(1, retried.imported)


class ArchiveFeedTests(unittest.TestCase):
    def test_archive_sources_use_the_configured_persistent_feeds(self) -> None:
        self.assertEqual("https://blog.bytebytego.com/feed", ARCHIVE_SOURCES["bytebytego"].subscription.feed_url)
        self.assertEqual("https://highscalability.com/rss/", ARCHIVE_SOURCES["highscalability"].subscription.feed_url)
        self.assertEqual("https://feeds.feedburner.com/martinkl", ARCHIVE_SOURCES["martin-kleppmann"].subscription.feed_url)

    def test_opml_includes_all_archive_publishers_under_system_design(self) -> None:
        subscriptions = parse_opml(Path(__file__).parents[1] / "feeds.opml")

        self.assertEqual(
            {
                ("ByteByteGo", "https://blog.bytebytego.com/feed"),
                ("High Scalability", "https://highscalability.com/rss/"),
                ("Martin Kleppmann", "https://feeds.feedburner.com/martinkl"),
            },
            {
                (subscription.name, subscription.feed_url)
                for subscription in subscriptions
                if subscription.topic == "System Design"
                and subscription.name in {"ByteByteGo", "High Scalability", "Martin Kleppmann"}
            },
        )


class ArchiveCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.articles = self.root / "vault" / "Sources" / "Articles"
        self.articles.mkdir(parents=True)
        self.config = ImporterConfig(self.articles.parents[2], self.articles, "defuddle")
        self.script = _load_archive_articles()
        self.script.__file__ = str(self.root / "archive_articles.py")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_cli_forwards_source_and_limit_and_reports_archive_counts(self) -> None:
        service = Mock()
        service.run.return_value = type(
            "Summary", (), {"discovered": 2, "pending": 1, "imported": 1, "recovered": 0, "failed": 0, "failed_sources": 0}
        )()
        output = StringIO()

        with (
            patch.object(self.script, "load_config", return_value=self.config),
            patch.object(self.script, "ArchiveImportService", return_value=service),
            contextlib.redirect_stdout(output),
        ):
            exit_code = self.script.main(["--source", "highscalability", "--limit", "5"])

        self.assertEqual(0, exit_code)
        service.run.assert_called_once_with(source="highscalability", limit=5)
        self.assertIn("discovered=2 pending=1 imported=1 recovered=0 failed=0 failed_sources=0", output.getvalue())


def _load_archive_articles() -> object:
    script_path = Path(__file__).parents[1] / "archive_articles.py"
    specification = importlib.util.spec_from_file_location("archive_articles_test", script_path)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not load archive_articles.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
