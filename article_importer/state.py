from __future__ import annotations

from dataclasses import dataclass, replace
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
    new_candidates: int = 0
    retry_candidates: int = 0
    pending_urls: frozenset[str] = frozenset()


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
        cutoff: datetime | None = None,
        observed_at: datetime | None = None,
        dry_run: bool = False,
        max_attempts: int | None = None,
    ) -> FeedBatch:
        """Return articles that should be imported for *subscription*.

        Every observation surfaces entries inside the supplied lookback window,
        along with eligible prior failures for processing.
        """
        observed_at = observed_at or datetime.now(timezone.utc)
        visible_entries = _unique_entries(entries)
        if dry_run:
            return self._dry_run_candidates(
                subscription, visible_entries, cutoff, observed_at, max_attempts
            )

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
                effective_entries = tuple(
                    _effective_entry(entry, None, observed_at) for entry in visible_entries
                )
                older_entries = [entry for entry in effective_entries if not _is_eligible(entry, cutoff)]
                eligible_entries = [entry for entry in effective_entries if _is_eligible(entry, cutoff)]
                connection.executemany(
                    """
                    INSERT INTO entries(
                        feed_url, article_url, title, published, status, output_path,
                        error_message, seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    [
                        (
                            subscription.feed_url,
                            entry.url,
                            entry.title,
                            _published_value(entry),
                            "failed" if _is_eligible(entry, cutoff) else "seeded",
                            timestamp,
                            timestamp,
                        )
                        for entry in effective_entries
                    ],
                )
                batch = FeedBatch(
                    True,
                    len(older_entries),
                    tuple(eligible_entries),
                    len(eligible_entries),
                )
            else:
                candidates: list[FeedEntry] = []
                new_candidates = 0
                retry_candidates = 0
                pending_urls: set[str] = set()
                for entry in visible_entries:
                    row = connection.execute(
                        "SELECT status, published, seen_at, attempts FROM entries WHERE feed_url = ? AND article_url = ?",
                        (subscription.feed_url, entry.url),
                    ).fetchone()
                    effective_entry = _effective_entry(entry, row, observed_at)
                    eligible = _is_eligible(effective_entry, cutoff)
                    if row is None:
                        connection.execute(
                            """
                            INSERT INTO entries(
                                feed_url, article_url, title, published, status, output_path,
                                error_message, seen_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                            """,
                            (
                                subscription.feed_url,
                                entry.url,
                                entry.title,
                                _published_value(effective_entry),
                                "failed" if eligible else "seeded",
                                timestamp,
                                timestamp,
                            ),
                        )
                        if eligible:
                            candidates.append(effective_entry)
                            new_candidates += 1
                    elif (
                        row[0] == "failed"
                        and eligible
                        and (max_attempts is None or int(row[3]) < max_attempts)
                    ):
                        candidates.append(effective_entry)
                        retry_candidates += 1
                    elif row[0] == "seeded" and eligible:
                        connection.execute(
                            """
                            UPDATE entries SET status = 'failed', published = ?, updated_at = ?
                            WHERE feed_url = ? AND article_url = ?
                            """,
                            (
                                _published_value(effective_entry),
                                timestamp,
                                subscription.feed_url,
                                entry.url,
                            ),
                        )
                        candidates.append(effective_entry)
                        new_candidates += 1
                    if connection.execute(
                        "SELECT 1 FROM pending_writes WHERE feed_url = ? AND article_url = ?",
                        (subscription.feed_url, entry.url),
                    ).fetchone() is not None:
                        pending_urls.add(entry.url)
                batch = FeedBatch(
                    False,
                    0,
                    tuple(candidates),
                    new_candidates,
                    retry_candidates,
                    frozenset(pending_urls),
                )

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

    def begin_note_write(self, feed_url: str, article_url: str) -> None:
        """Durably record a note write before the vault is modified."""
        timestamp = _utc_timestamp()
        connection = self._mutable_connection()
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO pending_writes(feed_url, article_url, started_at)
                VALUES (?, ?, ?)
                ON CONFLICT(feed_url, article_url) DO UPDATE SET started_at = excluded.started_at
                """,
                (feed_url, article_url, timestamp),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def mark_failed(self, feed_url: str, article_url: str, error: str) -> None:
        """Record an import failure so the currently visible article is retried."""
        self._record_outcome(
            feed_url=feed_url,
            article_url=article_url,
            status="failed",
            output_path=None,
            error_message=error,
        )

    def imported_output_path(self, article_url: str) -> str | None:
        """Return a successful output path for an article URL from any feed."""
        connection = self._mutable_connection()
        row = connection.execute(
            "SELECT output_path FROM entries WHERE article_url = ? AND status = 'imported' LIMIT 1",
            (article_url,),
        ).fetchone()
        return row[0] if row is not None and isinstance(row[0], str) else None

    def update_output_path(self, previous_path: str, output_path: str) -> None:
        """Update imported-note paths after an external vault move."""
        connection = self._mutable_connection()
        connection.execute("BEGIN")
        try:
            connection.execute(
                "UPDATE entries SET output_path = ? WHERE output_path = ?",
                (output_path, previous_path),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def failures(self) -> tuple[dict[str, object], ...]:
        """Return failed articles with their retry state."""
        connection = self._mutable_connection()
        return tuple(
            {
                "url": row[0],
                "feed": row[1],
                "attempts": row[2],
                "error": row[3],
                "updated": row[4],
            }
            for row in connection.execute(
                """
                SELECT article_url, feed_url, attempts, error_message, updated_at
                FROM entries WHERE status = 'failed'
                ORDER BY updated_at DESC
                """
            )
        )

    def reset_failure(self, article_url: str) -> bool:
        """Reset an exhausted failure so the next visible observation retries it."""
        connection = self._mutable_connection()
        cursor = connection.execute(
            """
            UPDATE entries SET attempts = 0, error_message = NULL
            WHERE article_url = ? AND status = 'failed'
            """,
            (article_url,),
        )
        return cursor.rowcount > 0

    def _dry_run_candidates(
        self,
        subscription: FeedSubscription,
        visible_entries: tuple[FeedEntry, ...],
        cutoff: datetime | None,
        observed_at: datetime,
        max_attempts: int | None,
    ) -> FeedBatch:
        if not self._path.is_file():
            return _new_feed_batch(visible_entries, cutoff, observed_at)

        connection = sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "feeds" not in tables:
                return _new_feed_batch(visible_entries, cutoff, observed_at)

            existing_feed = connection.execute(
                "SELECT 1 FROM feeds WHERE feed_url = ?", (subscription.feed_url,)
            ).fetchone()
            if existing_feed is None:
                return _new_feed_batch(visible_entries, cutoff, observed_at)
            if "entries" not in tables:
                candidates = tuple(
                    effective_entry
                    for entry in visible_entries
                    if _is_eligible(
                        effective_entry := _effective_entry(entry, None, observed_at), cutoff
                    )
                )
                return FeedBatch(False, 0, candidates, len(candidates))

            has_pending_writes = "pending_writes" in tables
            entry_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(entries)")
            }
            attempts_expression = "attempts" if "attempts" in entry_columns else "0"
            candidates: list[FeedEntry] = []
            new_candidates = 0
            retry_candidates = 0
            pending_urls: set[str] = set()
            for entry in visible_entries:
                row = connection.execute(
                    f"SELECT status, published, seen_at, {attempts_expression} FROM entries WHERE feed_url = ? AND article_url = ?",
                    (subscription.feed_url, entry.url),
                ).fetchone()
                effective_entry = _effective_entry(entry, row, observed_at)
                eligible = _is_eligible(effective_entry, cutoff)
                if row is None and eligible:
                    candidates.append(effective_entry)
                    new_candidates += 1
                elif (
                    row is not None
                    and row[0] == "failed"
                    and eligible
                    and (max_attempts is None or int(row[3]) < max_attempts)
                ):
                    candidates.append(effective_entry)
                    retry_candidates += 1
                elif row is not None and row[0] == "seeded" and eligible:
                    candidates.append(effective_entry)
                    new_candidates += 1
                if has_pending_writes and connection.execute(
                    "SELECT 1 FROM pending_writes WHERE feed_url = ? AND article_url = ?",
                    (subscription.feed_url, entry.url),
                ).fetchone() is not None:
                    pending_urls.add(entry.url)
            return FeedBatch(
                False,
                0,
                tuple(candidates),
                new_candidates,
                retry_candidates,
                frozenset(pending_urls),
            )
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
                attempts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(feed_url, article_url)
            );
            CREATE TABLE IF NOT EXISTS pending_writes(
                feed_url TEXT,
                article_url TEXT,
                started_at TEXT,
                PRIMARY KEY(feed_url, article_url)
            );
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)")}
        if "attempts" not in columns:
            connection.execute(
                "ALTER TABLE entries ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
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
                        THEN entries.updated_at ELSE excluded.updated_at END,
                    attempts = CASE
                        WHEN entries.status = 'imported' AND excluded.status = 'failed'
                        THEN entries.attempts
                        WHEN excluded.status = 'failed' THEN entries.attempts + 1
                        ELSE 0 END
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
            connection.execute(
                "DELETE FROM pending_writes WHERE feed_url = ? AND article_url = ?",
                (feed_url, article_url),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _effective_entry(
    entry: FeedEntry, row: tuple[object, ...] | None, observed_at: datetime
) -> FeedEntry:
    if entry.published is not None:
        return replace(entry, publication_date_source="feed")
    if row is not None:
        stored_time = _parse_stored_timestamp(row[1]) or _parse_stored_timestamp(row[2])
        if stored_time is not None:
            return replace(entry, published=stored_time, publication_date_source="observed")
    return replace(entry, published=observed_at, publication_date_source="observed")


def _parse_stored_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _new_feed_batch(
    visible_entries: tuple[FeedEntry, ...], cutoff: datetime | None, observed_at: datetime
) -> FeedBatch:
    effective_entries = tuple(
        _effective_entry(entry, None, observed_at) for entry in visible_entries
    )
    candidates = tuple(entry for entry in effective_entries if _is_eligible(entry, cutoff))
    return FeedBatch(
        True,
        len(effective_entries) - len(candidates),
        candidates,
        len(candidates),
    )


def _is_eligible(entry: FeedEntry, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    if entry.published is None:
        return False
    published = entry.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(timezone.utc) >= cutoff


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
