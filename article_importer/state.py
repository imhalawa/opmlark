from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

from article_importer.models import FeedEntry, FeedSubscription


@dataclass(frozen=True)
class FeedBatch:
    first_seen: bool
    seeded: int
    candidates: tuple[FeedEntry, ...]


class StateStore:
    """Persist feed observations and article import outcomes in SQLite."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def candidates(
        self,
        subscription: FeedSubscription,
        entries: Iterable[FeedEntry],
        dry_run: bool = False,
    ) -> FeedBatch:
        """Return articles that should be imported for *subscription*.

        The first observation of a feed establishes a no-backfill baseline. Later
        observations surface new articles and prior failures for processing.
        """
        visible_entries = _unique_entries(entries)
        if dry_run:
            return self._dry_run_candidates(subscription, visible_entries)

        timestamp = _utc_timestamp()
        connection = self._mutable_connection()
        connection.execute("BEGIN")
        try:
            existing_feed = connection.execute(
                "SELECT 1 FROM feeds WHERE feed_url = ?", (subscription.feed_url,)
            ).fetchone()
            if existing_feed is None:
                connection.execute(
                    "INSERT INTO feeds(feed_url, name, topic, initialized_at) VALUES (?, ?, ?, ?)",
                    (subscription.feed_url, subscription.name, subscription.topic, timestamp),
                )
                connection.executemany(
                    """
                    INSERT INTO entries(
                        feed_url, article_url, title, published, status, output_path,
                        error_message, seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'seeded', NULL, NULL, ?, ?)
                    """,
                    [
                        (
                            subscription.feed_url,
                            entry.url,
                            entry.title,
                            _published_value(entry),
                            timestamp,
                            timestamp,
                        )
                        for entry in visible_entries
                    ],
                )
                batch = FeedBatch(True, len(visible_entries), ())
            else:
                candidates: list[FeedEntry] = []
                for entry in visible_entries:
                    row = connection.execute(
                        "SELECT status FROM entries WHERE feed_url = ? AND article_url = ?",
                        (subscription.feed_url, entry.url),
                    ).fetchone()
                    if row is None:
                        connection.execute(
                            """
                            INSERT INTO entries(
                                feed_url, article_url, title, published, status, output_path,
                                error_message, seen_at, updated_at
                            ) VALUES (?, ?, ?, ?, 'failed', NULL, NULL, ?, ?)
                            """,
                            (
                                subscription.feed_url,
                                entry.url,
                                entry.title,
                                _published_value(entry),
                                timestamp,
                                timestamp,
                            ),
                        )
                        candidates.append(entry)
                    elif row[0] == "failed":
                        candidates.append(entry)
                batch = FeedBatch(False, 0, tuple(candidates))

            connection.commit()
            return batch
        except BaseException:
            connection.rollback()
            raise

    def mark_imported(self, feed_url: str, article_url: str, output_path: str) -> None:
        """Record a successfully written article note."""
        self._record_outcome(
            feed_url=feed_url,
            article_url=article_url,
            status="imported",
            output_path=output_path,
            error_message=None,
        )

    def mark_failed(self, feed_url: str, article_url: str, error: str) -> None:
        """Record an import failure so the currently visible article is retried."""
        self._record_outcome(
            feed_url=feed_url,
            article_url=article_url,
            status="failed",
            output_path=None,
            error_message=error,
        )

    def _dry_run_candidates(
        self, subscription: FeedSubscription, visible_entries: tuple[FeedEntry, ...]
    ) -> FeedBatch:
        if not self._path.is_file():
            return FeedBatch(True, len(visible_entries), ())

        connection = sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "feeds" not in tables:
                return FeedBatch(True, len(visible_entries), ())

            existing_feed = connection.execute(
                "SELECT 1 FROM feeds WHERE feed_url = ?", (subscription.feed_url,)
            ).fetchone()
            if existing_feed is None:
                return FeedBatch(True, len(visible_entries), ())
            if "entries" not in tables:
                return FeedBatch(False, 0, visible_entries)

            candidates = tuple(
                entry
                for entry in visible_entries
                if (row := connection.execute(
                    "SELECT status FROM entries WHERE feed_url = ? AND article_url = ?",
                    (subscription.feed_url, entry.url),
                ).fetchone()) is None
                or row[0] == "failed"
            )
            return FeedBatch(False, 0, candidates)
        finally:
            connection.close()

    def _mutable_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self._path, isolation_level=None)
            self._create_schema(self._connection)
        return self._connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS feeds(
                feed_url TEXT PRIMARY KEY,
                name TEXT,
                topic TEXT,
                initialized_at TEXT
            );
            CREATE TABLE IF NOT EXISTS entries(
                feed_url TEXT,
                article_url TEXT,
                title TEXT,
                published TEXT,
                status TEXT CHECK(status IN ('seeded', 'imported', 'failed')),
                output_path TEXT,
                error_message TEXT,
                seen_at TEXT,
                updated_at TEXT,
                PRIMARY KEY(feed_url, article_url)
            );
            """
        )

    def _record_outcome(
        self,
        *,
        feed_url: str,
        article_url: str,
        status: str,
        output_path: str | None,
        error_message: str | None,
    ) -> None:
        timestamp = _utc_timestamp()
        connection = self._mutable_connection()
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO entries(
                    feed_url, article_url, title, published, status, output_path,
                    error_message, seen_at, updated_at
                ) VALUES (?, ?, '', NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_url, article_url) DO UPDATE SET
                    status = CASE
                        WHEN entries.status = 'imported' AND excluded.status = 'failed'
                        THEN entries.status ELSE excluded.status END,
                    output_path = CASE
                        WHEN entries.status = 'imported' AND excluded.status = 'failed'
                        THEN entries.output_path ELSE excluded.output_path END,
                    error_message = CASE
                        WHEN entries.status = 'imported' AND excluded.status = 'failed'
                        THEN entries.error_message ELSE excluded.error_message END,
                    updated_at = CASE
                        WHEN entries.status = 'imported' AND excluded.status = 'failed'
                        THEN entries.updated_at ELSE excluded.updated_at END
                """,
                (
                    feed_url,
                    article_url,
                    status,
                    output_path,
                    error_message,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _unique_entries(entries: Iterable[FeedEntry]) -> tuple[FeedEntry, ...]:
    seen_urls: set[str] = set()
    unique: list[FeedEntry] = []
    for entry in entries:
        if entry.url not in seen_urls:
            seen_urls.add(entry.url)
            unique.append(entry)
    return tuple(unique)


def _published_value(entry: FeedEntry) -> str | None:
    if entry.published is None:
        return None
    published = entry.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(timezone.utc).isoformat()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
