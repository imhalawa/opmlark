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
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._create_schema()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self._connection.close()

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
        timestamp = _utc_timestamp()
        self._connection.execute("BEGIN")
        try:
            existing_feed = self._connection.execute(
                "SELECT 1 FROM feeds WHERE feed_url = ?", (subscription.feed_url,)
            ).fetchone()
            if existing_feed is None:
                self._connection.execute(
                    "INSERT INTO feeds(feed_url, name, topic, initialized_at) VALUES (?, ?, ?, ?)",
                    (subscription.feed_url, subscription.name, subscription.topic, timestamp),
                )
                self._connection.executemany(
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
                    row = self._connection.execute(
                        "SELECT status FROM entries WHERE feed_url = ? AND article_url = ?",
                        (subscription.feed_url, entry.url),
                    ).fetchone()
                    if row is None:
                        self._connection.execute(
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

            if dry_run:
                self._connection.rollback()
            else:
                self._connection.commit()
            return batch
        except BaseException:
            self._connection.rollback()
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

    def _create_schema(self) -> None:
        self._connection.executescript(
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
        self._connection.execute("BEGIN")
        try:
            self._connection.execute(
                """
                INSERT INTO entries(
                    feed_url, article_url, title, published, status, output_path,
                    error_message, seen_at, updated_at
                ) VALUES (?, ?, '', NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_url, article_url) DO UPDATE SET
                    status = excluded.status,
                    output_path = excluded.output_path,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
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
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
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
    if entry.published.tzinfo is None:
        return entry.published.isoformat()
    return entry.published.astimezone(timezone.utc).isoformat()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
