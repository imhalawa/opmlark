from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from article_importer.configuration import ConfigurationError, load_config
from article_importer.models import FeedSubscription
from article_importer.parsing import parse_feed, parse_opml
from tests.fixtures import (
    ATOM,
    ATOM_WITH_DEFAULT_ALTERNATE,
    ATOM_WITH_EMPTY_ALTERNATE,
    OPML,
    RSS,
    RSS_WITH_DUPLICATES,
)


class ParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.temp = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_opml_uses_parent_outline_as_topic(self) -> None:
        path = self.temp / "feeds.opml"
        path.write_bytes(OPML)

        self.assertEqual(
            [
                FeedSubscription(
                    "System Design",
                    "ByteByteGo",
                    "https://example.test/feed",
                    "https://example.test",
                )
            ],
            parse_opml(path),
        )

    def test_rss_and_atom_links_are_read(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")

        self.assertEqual("https://example.test/rss", parse_feed(RSS, feed)[0].url)
        self.assertEqual("https://example.test/atom", parse_feed(ATOM, feed)[0].url)

    def test_atom_link_without_rel_is_preferred_to_self_link(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")

        self.assertEqual(
            "https://example.test/default-alternate",
            parse_feed(ATOM_WITH_DEFAULT_ALTERNATE, feed)[0].url,
        )

    def test_atom_empty_alternate_falls_back_to_usable_link(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")

        self.assertEqual(
            "https://example.test/usable-fallback",
            parse_feed(ATOM_WITH_EMPTY_ALTERNATE, feed)[0].url,
        )

    def test_feed_discards_duplicate_and_missing_urls(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")

        entries = parse_feed(RSS_WITH_DUPLICATES, feed)

        self.assertEqual(["https://example.test/entry"], [entry.url for entry in entries])

    def test_feed_parses_rss_and_atom_publication_dates(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")

        rss_entry = parse_feed(RSS, feed)[0]
        atom_entry = parse_feed(ATOM, feed)[0]

        self.assertEqual("2025-07-01T12:00:00+00:00", rss_entry.published.isoformat())
        self.assertEqual("2025-07-02T12:00:00+00:00", atom_entry.published.isoformat())

    def test_config_requires_articles_directory(self) -> None:
        config = self.temp / "config.toml"
        config.write_text('[importer]\nvault_path = "C:/missing"\n', encoding="utf-8")

        with self.assertRaisesRegex(ConfigurationError, "Sources/Articles"):
            load_config(config)

    def test_config_rejects_non_table_importer_value(self) -> None:
        config = self.temp / "config.toml"
        config.write_text('importer = "invalid"\n', encoding="utf-8")

        with self.assertRaisesRegex(ConfigurationError, "importer"):
            load_config(config)

    def test_config_resolves_relative_executable_from_config_directory(self) -> None:
        vault = self.temp / "vault"
        articles = vault / "Sources" / "Articles"
        articles.mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\nvault_path = "vault"\ndefuddle_executable = "tools/defuddle.exe"\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual(vault, loaded.vault_path)
        self.assertEqual(articles, loaded.articles_path)
        self.assertEqual(str(self.temp / "tools" / "defuddle.exe"), loaded.defuddle_executable)

    def test_config_keeps_bare_executable_for_path_resolution(self) -> None:
        vault = self.temp / "vault"
        (vault / "Sources" / "Articles").mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\nvault_path = "vault"\ndefuddle_executable = "defuddle"\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual("defuddle", loaded.defuddle_executable)

    def test_config_reads_positive_lookback_days(self) -> None:
        vault = self.temp / "vault"
        (vault / "Sources" / "Articles").mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\nvault_path = "vault"\nlookback_days = 90\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual(90, loaded.lookback_days)


if __name__ == "__main__":
    unittest.main()
