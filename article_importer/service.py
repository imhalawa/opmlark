from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from urllib.request import Request, urlopen

from article_importer.configuration import ImporterConfig
from article_importer.defuddle import DefuddledArticle, run_defuddle
from article_importer.models import FeedSubscription
from article_importer.notes import build_frontmatter, create_note, find_note_for_source
from article_importer.parsing import parse_feed
from article_importer.state import StateStore


@dataclass(frozen=True)
class RunSummary:
    seeded: int = 0
    imported: int = 0
    failed_entries: int = 0
    failed_feeds: int = 0
    would_import: int = 0
    would_retry: int = 0


class ImportService:
    """Fetch subscribed feeds and import only newly observed articles."""

    def __init__(
        self,
        config: ImporterConfig,
        subscriptions: Iterable[FeedSubscription],
        state_path: Path,
        *,
        fetch_bytes: Callable[[str], bytes] | None = None,
        defuddle: Callable[[str, str], DefuddledArticle] = run_defuddle,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._subscriptions = tuple(subscriptions)
        self._state_path = state_path
        self._fetch_bytes = fetch_bytes or fetch_feed_bytes
        self._defuddle = defuddle
        self._logger = logger or logging.getLogger(__name__)

    def run(self, dry_run: bool) -> RunSummary:
        """Process every feed, recording failures without stopping later feeds."""
        summary = RunSummary()
        observed_at = datetime.now(timezone.utc)
        cutoff = observed_at - timedelta(days=self._config.lookback_days)
        with StateStore(self._state_path) as state:
            for subscription in self._subscriptions:
                try:
                    entries = parse_feed(self._fetch_bytes(subscription.feed_url), subscription)
                    batch = state.candidates(
                        subscription,
                        entries,
                        cutoff=cutoff,
                        observed_at=observed_at,
                        dry_run=dry_run,
                    )
                except Exception as error:
                    self._logger.error("Failed feed %s: %s", subscription.feed_url, error)
                    summary = _with(summary, failed_feeds=summary.failed_feeds + 1)
                    continue

                summary = _with(summary, seeded=summary.seeded + batch.seeded)
                if dry_run:
                    summary = _with(
                        summary,
                        would_import=summary.would_import + batch.new_candidates,
                        would_retry=summary.would_retry + batch.retry_candidates,
                    )
                    continue

                for entry in batch.candidates:
                    note: Path | None = None
                    try:
                        if entry.url in batch.pending_urls:
                            note = find_note_for_source(self._config.articles_path, entry.url)
                            if note is not None:
                                state.mark_imported(
                                    entry.subscription.feed_url, entry.url, str(note)
                                )
                                continue
                        state.begin_note_write(entry.subscription.feed_url, entry.url)
                        article = self._defuddle(entry.url, self._config.defuddle_executable)
                        note = create_note(
                            self._config.articles_path,
                            build_frontmatter(article, entry, datetime.now(timezone.utc)),
                            article.markdown,
                        )
                        state.mark_imported(entry.subscription.feed_url, entry.url, str(note))
                    except Exception as error:
                        if note is None:
                            try:
                                state.mark_failed(
                                    entry.subscription.feed_url, entry.url, str(error)
                                )
                            except Exception as state_error:
                                self._logger.error(
                                    "Failed to record article failure %s: %s",
                                    entry.url,
                                    state_error,
                                )
                        self._logger.error("Failed article %s: %s", entry.url, error)
                        summary = _with(
                            summary, failed_entries=summary.failed_entries + 1
                        )
                    else:
                        summary = _with(summary, imported=summary.imported + 1)
        return summary


def fetch_feed_bytes(url: str) -> bytes:
    """Fetch a feed using the production request policy."""
    request = Request(url, headers={"User-Agent": "opml-defuddle-articles/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def _with(summary: RunSummary, **changes: int) -> RunSummary:
    return RunSummary(
        seeded=changes.get("seeded", summary.seeded),
        imported=changes.get("imported", summary.imported),
        failed_entries=changes.get("failed_entries", summary.failed_entries),
        failed_feeds=changes.get("failed_feeds", summary.failed_feeds),
        would_import=changes.get("would_import", summary.would_import),
        would_retry=changes.get("would_retry", summary.would_retry),
    )
