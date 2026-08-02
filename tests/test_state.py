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
    def test_failed_entry_stops_retrying_after_attempt_budget(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with StateStore(path) as state:
                first = state.candidates(SUBSCRIPTION, [ENTRY], max_attempts=2)
                self.assertEqual((ENTRY,), first.candidates)
                state.mark_failed(SUBSCRIPTION.feed_url, ENTRY.url, "first")
                second = state.candidates(SUBSCRIPTION, [ENTRY], max_attempts=2)
                self.assertEqual((ENTRY,), second.candidates)
                state.mark_failed(SUBSCRIPTION.feed_url, ENTRY.url, "second")
                exhausted = state.candidates(SUBSCRIPTION, [ENTRY], max_attempts=2)

            self.assertEqual((), exhausted.candidates)

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "articles.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_first_observation_seeds_an_entry_outside_the_lookback(self) -> None:
        with StateStore(self.database) as state:
            batch = state.candidates(
                SUBSCRIPTION,
                [ENTRY],
                cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
                observed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            )

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

        self.assertEqual((NEW.url,), tuple(entry.url for entry in batch.candidates))

    def test_dry_run_returns_first_seen_seed_count_without_persisting_it(self) -> None:
        with StateStore(self.database) as state:
            preview = state.candidates(
                SUBSCRIPTION,
                [ENTRY],
                cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
                observed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
                dry_run=True,
            )
            committed = state.candidates(
                SUBSCRIPTION,
                [ENTRY],
                cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
                observed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            )

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

        self.assertEqual((NEW.url,), tuple(entry.url for entry in preview.candidates))
        self.assertEqual((NEW.url,), tuple(entry.url for entry in committed.candidates))

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

        self.assertEqual((NEW.url,), tuple(entry.url for entry in batch.candidates))
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

    def test_new_feed_candidates_include_only_recent_and_undated_entries(self) -> None:
        observed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        cutoff = datetime(2026, 4, 19, tzinfo=timezone.utc)
        old = FeedEntry("Old", "https://example.test/old", datetime(2026, 1, 1, tzinfo=timezone.utc), SUBSCRIPTION)
        recent = FeedEntry("Recent", "https://example.test/recent", datetime(2026, 7, 1, tzinfo=timezone.utc), SUBSCRIPTION)
        undated = FeedEntry("Undated", "https://example.test/undated", None, SUBSCRIPTION)

        with StateStore(self.database) as state:
            batch = state.candidates(
                SUBSCRIPTION, [old, recent, undated], cutoff=cutoff, observed_at=observed_at
            )

        self.assertEqual({recent.url, undated.url}, {entry.url for entry in batch.candidates})
        self.assertEqual(1, batch.seeded)
        observed_entry = next(entry for entry in batch.candidates if entry.url == undated.url)
        self.assertEqual("observed", observed_entry.publication_date_source)

    def test_recent_seeded_entry_is_promoted_but_old_seeded_entry_stays_ignored(self) -> None:
        observed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        cutoff = datetime(2026, 4, 19, tzinfo=timezone.utc)
        old = FeedEntry("Old", "https://example.test/old", datetime(2026, 1, 1, tzinfo=timezone.utc), SUBSCRIPTION)
        recent = FeedEntry("Recent", "https://example.test/recent", datetime(2026, 7, 1, tzinfo=timezone.utc), SUBSCRIPTION)

        with StateStore(self.database) as state:
            state.candidates(SUBSCRIPTION, [old, recent])
            batch = state.candidates(
                SUBSCRIPTION, [old, recent], cutoff=cutoff, observed_at=observed_at
            )

        self.assertEqual((recent,), batch.candidates)

    def test_dry_run_previews_recent_entries_for_a_new_feed(self) -> None:
        observed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
        cutoff = datetime(2026, 4, 19, tzinfo=timezone.utc)
        old = FeedEntry("Old", "https://example.test/old", datetime(2026, 1, 1, tzinfo=timezone.utc), SUBSCRIPTION)
        recent = FeedEntry("Recent", "https://example.test/recent", datetime(2026, 7, 1, tzinfo=timezone.utc), SUBSCRIPTION)

        with StateStore(self.database) as state:
            preview = state.candidates(
                SUBSCRIPTION,
                [old, recent],
                cutoff=cutoff,
                observed_at=observed_at,
                dry_run=True,
            )

        self.assertEqual(1, preview.seeded)
        self.assertEqual((recent,), preview.candidates)
        self.assertEqual(1, preview.new_candidates)

    def test_undated_retry_keeps_its_first_observation_time(self) -> None:
        undated = FeedEntry("Undated", "https://example.test/undated", None, SUBSCRIPTION)
        first_observed = datetime(2026, 4, 1, tzinfo=timezone.utc)

        with StateStore(self.database) as state:
            first = state.candidates(
                SUBSCRIPTION,
                [undated],
                cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
                observed_at=first_observed,
            )
            state.mark_failed(SUBSCRIPTION.feed_url, undated.url, "temporary failure")
            later = state.candidates(
                SUBSCRIPTION,
                [undated],
                cutoff=datetime(2026, 7, 2, tzinfo=timezone.utc),
                observed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
            )

        self.assertEqual(("observed",), tuple(entry.publication_date_source for entry in first.candidates))
        self.assertEqual((), later.candidates)


if __name__ == "__main__":
    unittest.main()
