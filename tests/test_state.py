from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from article_importer.models import FeedEntry, FeedSubscription
from article_importer.state import StateStore


SUBSCRIPTION = FeedSubscription(
    topic="System Design",
    name="Example Feed",
    feed_url="https://example.test/feed",
)
ENTRY = FeedEntry(
    title="Existing article",
    url="https://example.test/existing",
    published=datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc),
    subscription=SUBSCRIPTION,
)
FAILED = FeedEntry(
    title="Failed article",
    url="https://example.test/failed",
    published=None,
    subscription=SUBSCRIPTION,
)
NEW = FeedEntry(
    title="New article",
    url="https://example.test/new",
    published=None,
    subscription=SUBSCRIPTION,
)


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "articles.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_first_observation_seeds_and_returns_no_candidates(self) -> None:
        with StateStore(self.database) as state:
            batch = state.candidates(SUBSCRIPTION, [ENTRY])

        self.assertTrue(batch.first_seen)
        self.assertEqual(1, batch.seeded)
        self.assertEqual((), batch.candidates)

    def test_failed_and_new_are_candidates_but_imported_is_not(self) -> None:
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            state.mark_imported(SUBSCRIPTION.feed_url, ENTRY.url, "Article - entry.md")
            state.mark_failed(SUBSCRIPTION.feed_url, FAILED.url, "timeout")
            batch = state.candidates(SUBSCRIPTION, [ENTRY, FAILED, NEW])

        self.assertFalse(batch.first_seen)
        self.assertEqual({FAILED.url, NEW.url}, {item.url for item in batch.candidates})

    def test_duplicate_visible_urls_are_returned_once(self) -> None:
        duplicate = FeedEntry(
            title="Duplicate title",
            url=NEW.url,
            published=None,
            subscription=SUBSCRIPTION,
        )
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            batch = state.candidates(SUBSCRIPTION, [NEW, duplicate])

        self.assertEqual((NEW,), batch.candidates)

    def test_dry_run_returns_first_seen_seed_count_without_persisting_it(self) -> None:
        with StateStore(self.database) as state:
            preview = state.candidates(SUBSCRIPTION, [ENTRY], dry_run=True)
            committed = state.candidates(SUBSCRIPTION, [ENTRY])

        self.assertTrue(preview.first_seen)
        self.assertEqual(1, preview.seeded)
        self.assertTrue(committed.first_seen)
        self.assertEqual(1, committed.seeded)

    def test_dry_run_against_new_path_creates_no_database_or_parent_directory(self) -> None:
        database = self.database.parent / "data" / "articles.sqlite3"

        with StateStore(database) as state:
            preview = state.candidates(SUBSCRIPTION, [ENTRY], dry_run=True)

        self.assertTrue(preview.first_seen)
        self.assertFalse(database.exists())
        self.assertFalse(database.parent.exists())

    def test_dry_run_does_not_track_new_candidates(self) -> None:
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            preview = state.candidates(SUBSCRIPTION, [NEW], dry_run=True)
            committed = state.candidates(SUBSCRIPTION, [NEW])

        self.assertEqual((NEW,), preview.candidates)
        self.assertEqual((NEW,), committed.candidates)

    def test_dry_run_does_not_change_existing_database_rows(self) -> None:
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])

        before_connection = sqlite3.connect(self.database)
        try:
            before = before_connection.execute(
                "SELECT article_url, status FROM entries ORDER BY article_url"
            ).fetchall()
        finally:
            before_connection.close()

        with StateStore(self.database) as state:
            batch = state.candidates(SUBSCRIPTION, [NEW], dry_run=True)

        after_connection = sqlite3.connect(self.database)
        try:
            after = after_connection.execute(
                "SELECT article_url, status FROM entries ORDER BY article_url"
            ).fetchall()
        finally:
            after_connection.close()

        self.assertEqual((NEW,), batch.candidates)
        self.assertEqual(before, after)

    def test_mark_failed_does_not_reenable_an_imported_entry(self) -> None:
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            state.mark_imported(SUBSCRIPTION.feed_url, ENTRY.url, "Article - entry.md")
            state.mark_failed(SUBSCRIPTION.feed_url, ENTRY.url, "stale timeout")
            batch = state.candidates(SUBSCRIPTION, [ENTRY])

        self.assertEqual((), batch.candidates)

    def test_naive_publication_time_is_stored_as_utc(self) -> None:
        naive_entry = FeedEntry(
            title="Naive publication time",
            url="https://example.test/naive-time",
            published=datetime(2025, 1, 2, 3, 4, 5),
            subscription=SUBSCRIPTION,
        )
        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [naive_entry])

        connection = sqlite3.connect(self.database)
        try:
            published = connection.execute(
                "SELECT published FROM entries WHERE article_url = ?", (naive_entry.url,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("2025-01-02T03:04:05+00:00", published)


if __name__ == "__main__":
    unittest.main()
