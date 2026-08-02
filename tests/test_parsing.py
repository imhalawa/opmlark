from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from article_importer.configuration import ConfigurationError, FeedCatalog, Schedule, load_config
from article_importer.models import FeedSubscription
from article_importer.parsing import CatalogError, parse_catalogs, parse_feed, parse_opml
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
        self.temp = Path(self.temporary_directory.name).resolve()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_opml_uses_parent_outline_as_topic(self) -> None:
        path = self.temp / "feeds.opml"
        path.write_bytes(OPML.replace(b'<outline text="ByteByteGo"', b'<outline id="bytebytego" text="ByteByteGo"'))

        self.assertEqual(
            [
                FeedSubscription(
                    "System Design",
                    "ByteByteGo",
                    "https://example.test/feed",
                    "https://example.test",
                    "bytebytego",
                )
            ],
            parse_opml(path),
        )

    def test_catalogs_combine_enabled_files_with_catalog_folder_inheritance(self) -> None:
        first = self.temp / "system-design.opml"
        first.write_text(
            '<opml><body><outline text="System Design"><outline id="bytebytego" text="ByteByteGo" xmlUrl="https://example.test/bytebytego"/></outline></body></opml>',
            encoding="utf-8",
        )
        second = self.temp / "psychology.opml"
        second.write_text(
            '<opml><body><outline text="Psychology / ADHD"><outline id="chadd" text="CHADD" xmlUrl="https://example.test/chadd" folder="ADHD"/></outline></body></opml>',
            encoding="utf-8",
        )

        subscriptions = parse_catalogs(
            (
                FeedCatalog("system-design", first, folder="Engineering"),
                FeedCatalog("psychology", second, folder="Psychology"),
            )
        )

        self.assertEqual(
            [
                FeedSubscription(
                    "System Design", "ByteByteGo", "https://example.test/bytebytego", None,
                    "bytebytego", "Engineering",
                ),
                FeedSubscription(
                    "Psychology / ADHD", "CHADD", "https://example.test/chadd", None,
                    "chadd", "ADHD",
                ),
            ],
            subscriptions,
        )

    def test_catalogs_skip_disabled_sources_and_catalogs(self) -> None:
        enabled = self.temp / "enabled.opml"
        enabled.write_text(
            '<opml><body><outline text="Topic"><outline id="included" text="Included" xmlUrl="https://example.test/included"/><outline id="disabled-in-opml" text="Disabled" xmlUrl="https://example.test/disabled" enabled="false"/><outline id="disabled-in-config" text="Disabled in config" xmlUrl="https://example.test/config"/></outline></body></opml>',
            encoding="utf-8",
        )
        disabled = self.temp / "disabled.opml"
        disabled.write_text(
            '<opml><body><outline text="Topic"><outline id="other" text="Other" xmlUrl="https://example.test/other"/></outline></body></opml>',
            encoding="utf-8",
        )

        subscriptions = parse_catalogs(
            (FeedCatalog("enabled", enabled), FeedCatalog("disabled", disabled, enabled=False)),
            disabled_sources=frozenset({"disabled-in-config"}),
        )

        self.assertEqual(["included"], [item.source_id for item in subscriptions])

    def test_catalogs_reject_duplicate_source_ids(self) -> None:
        first = self.temp / "first.opml"
        first.write_text(
            '<opml><body><outline text="Topic"><outline id="duplicate" text="First" xmlUrl="https://example.test/first"/></outline></body></opml>',
            encoding="utf-8",
        )
        second = self.temp / "second.opml"
        second.write_text(
            '<opml><body><outline text="Topic"><outline id="duplicate" text="Second" xmlUrl="https://example.test/second"/></outline></body></opml>',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalogError, "duplicate"):
            parse_catalogs((FeedCatalog("first", first), FeedCatalog("second", second)))

    def test_config_reads_enabled_catalogs_and_disable_lists(self) -> None:
        vault = self.temp / "vault"
        (vault / "Sources" / "Articles").mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\nvault_path = "vault"\nlookback_days = 90\n'
            '[feed_catalog]\ndisabled_catalogs = ["disabled"]\ndisabled_sources = ["blocked"]\n'
            '[[feed_catalogs]]\nid = "system-design"\npath = "feeds/system-design.opml"\nfolder = "Engineering"\n'
            '[[feed_catalogs]]\nid = "disabled"\npath = "feeds/disabled.opml"\nenabled = true\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual(
            (FeedCatalog("system-design", self.temp / "feeds" / "system-design.opml", True, "Engineering"),),
            loaded.feed_catalogs,
        )
        self.assertEqual(frozenset({"blocked"}), loaded.disabled_sources)

    def test_config_reads_all_portable_schedule_types(self) -> None:
        articles = self.temp / "articles"
        articles.mkdir()
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\noutput_path = "articles"\nlookback_days = 90\n'
            '[[schedules]]\nid = "morning"\nfrequency = "daily"\nat = "07:00"\n'
            '[[schedules]]\nid = "weekend"\nfrequency = "weekly"\ndays = ["SAT", "sun"]\nat = "09:30"\n'
            '[[schedules]]\nid = "monthly-review"\nfrequency = "monthly"\nday = 31\nat = "18:00"\n'
            '[[schedules]]\nid = "special-import"\nfrequency = "once"\ndate = "2026-09-15"\nat = "12:00"\nenabled = false\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual(
            (
                Schedule("morning", "daily", "07:00"),
                Schedule("weekend", "weekly", "09:30", days=("sat", "sun")),
                Schedule("monthly-review", "monthly", "18:00", day=31),
                Schedule("special-import", "once", "12:00", False, date="2026-09-15"),
            ),
            loaded.schedules,
        )

    def test_config_rejects_invalid_schedule_shapes(self) -> None:
        articles = self.temp / "articles"
        articles.mkdir()
        prefix = '[importer]\noutput_path = "articles"\nlookback_days = 90\n'
        invalid_blocks = {
            "duplicate schedule id": (
                '[[schedules]]\nid = "same"\nfrequency = "daily"\nat = "07:00"\n'
                '[[schedules]]\nid = "same"\nfrequency = "daily"\nat = "08:00"\n'
            ),
            "schedules.id": '[[schedules]]\nid = "Bad ID"\nfrequency = "daily"\nat = "07:00"\n',
            "schedules.at": '[[schedules]]\nid = "bad-time"\nfrequency = "daily"\nat = "7:00"\n',
            "schedules.frequency": '[[schedules]]\nid = "raw"\nfrequency = "cron"\nat = "07:00"\n',
            "schedules.days": '[[schedules]]\nid = "empty"\nfrequency = "weekly"\ndays = []\nat = "07:00"\n',
            "duplicate weekdays": '[[schedules]]\nid = "dupe-days"\nfrequency = "weekly"\ndays = ["mon", "MON"]\nat = "07:00"\n',
            "schedules.day": '[[schedules]]\nid = "bad-day"\nfrequency = "monthly"\nday = 32\nat = "07:00"\n',
            "schedules.date": '[[schedules]]\nid = "bad-date"\nfrequency = "once"\ndate = "2026-02-30"\nat = "07:00"\n',
            "unexpected fields": '[[schedules]]\nid = "extra"\nfrequency = "daily"\nat = "07:00"\nday = 1\n',
        }
        for message, block in invalid_blocks.items():
            with self.subTest(message=message):
                config = self.temp / "config.toml"
                config.write_text(prefix + block, encoding="utf-8")
                with self.assertRaisesRegex(ConfigurationError, message):
                    load_config(config)

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
            '[importer]\nvault_path = "vault"\ndefuddle_executable = "tools/defuddle.exe"\nlookback_days = 90\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual(vault, loaded.vault_path)
        self.assertEqual(articles, loaded.articles_path)
        self.assertEqual(str(self.temp / "tools" / "defuddle.exe"), loaded.defuddle_executable)

    @patch("article_importer.configuration.shutil.which")
    def test_config_resolves_bare_executable_from_path(self, which: object) -> None:
        which.return_value = "C:/tools/defuddle.cmd"
        vault = self.temp / "vault"
        (vault / "Sources" / "Articles").mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text(
            '[importer]\nvault_path = "vault"\ndefuddle_executable = "defuddle"\nlookback_days = 90\n',
            encoding="utf-8",
        )

        loaded = load_config(config)

        self.assertEqual("C:/tools/defuddle.cmd", loaded.defuddle_executable)

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

    def test_config_requires_lookback_days(self) -> None:
        vault = self.temp / "vault"
        (vault / "Sources" / "Articles").mkdir(parents=True)
        config = self.temp / "config.toml"
        config.write_text('[importer]\nvault_path = "vault"\n', encoding="utf-8")

        with self.assertRaisesRegex(ConfigurationError, "lookback_days"):
            load_config(config)


if __name__ == "__main__":
    unittest.main()
