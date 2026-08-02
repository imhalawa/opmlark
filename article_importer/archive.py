from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import logging
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree

from article_importer.configuration import ImporterConfig
from article_importer.defuddle import DefuddledArticle, run_defuddle
from article_importer.models import FeedEntry, FeedSubscription
from article_importer.notes import build_frontmatter, create_note, find_note_for_source
from article_importer.state import StateStore


BYTEBYTEGO_FEED = "https://blog.bytebytego.com/feed"
HIGHSCALABILITY_FEED = "https://highscalability.com/rss/"
MARTIN_KLEPPMANN_FEED = "https://feeds.feedburner.com/martinkl"


@dataclass(frozen=True)
class ArchiveSource:
    key: str
    subscription: FeedSubscription
    discover: Callable[[Callable[[str], bytes]], tuple[str, ...]]


@dataclass(frozen=True)
class ArchiveRunSummary:
    discovered: int = 0
    pending: int = 0
    imported: int = 0
    recovered: int = 0
    failed: int = 0
    failed_sources: int = 0


ARCHIVE_SOURCES = {
    "bytebytego": ArchiveSource(
        "bytebytego",
        FeedSubscription("System Design", "ByteByteGo", BYTEBYTEGO_FEED),
        lambda fetch: discover_bytebytego_urls(fetch),
    ),
    "highscalability": ArchiveSource(
        "highscalability",
        FeedSubscription("System Design", "High Scalability", HIGHSCALABILITY_FEED),
        lambda fetch: discover_highscalability_urls(fetch),
    ),
    "martin-kleppmann": ArchiveSource(
        "martin-kleppmann",
        FeedSubscription("System Design", "Martin Kleppmann", MARTIN_KLEPPMANN_FEED),
        lambda fetch: discover_martin_kleppmann_urls(fetch),
    ),
}


class ArchiveImportService:
    """Discover and import historic articles without involving the daily feed run."""

    def __init__(
        self,
        config: ImporterConfig,
        state_path: Path,
        *,
        fetch_bytes: Callable[[str], bytes] = None,
        discoverers: dict[str, Callable[[Callable[[str], bytes]], tuple[str, ...]]] | None = None,
        defuddle: Callable[[str, str], DefuddledArticle] = run_defuddle,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._state_path = state_path
        self._fetch_bytes = fetch_bytes or fetch_archive_bytes
        self._discoverers = discoverers or {
            key: source.discover for key, source in ARCHIVE_SOURCES.items()
        }
        self._defuddle = defuddle
        self._logger = logger or logging.getLogger(__name__)

    def run(self, source: str = "all", limit: int | None = None) -> ArchiveRunSummary:
        """Import the selected archives, preserving state so runs can resume."""
        selected = select_archive_sources(source)
        remaining = limit
        summary = ArchiveRunSummary()
        seen_urls: set[str] = set()

        with StateStore(self._state_path) as state:
            for archive_source in selected:
                try:
                    discovered = self._discoverers[archive_source.key](self._fetch_bytes)
                except Exception as error:
                    self._logger.error("Failed archive discovery %s: %s", archive_source.key, error)
                    summary = _with_summary(
                        summary, failed_sources=summary.failed_sources + 1
                    )
                    continue

                urls = tuple(url for url in discovered if url not in seen_urls)
                seen_urls.update(urls)
                summary = _with_summary(summary, discovered=summary.discovered + len(urls))
                entries = tuple(
                    FeedEntry(url, url, None, archive_source.subscription) for url in urls
                )
                batch = state.candidates(
                    archive_source.subscription,
                    entries,
                    cutoff=None,
                    max_attempts=self._config.max_attempts,
                )
                summary = _with_summary(summary, pending=summary.pending + len(batch.candidates))

                for entry in batch.candidates:
                    if remaining is not None and remaining <= 0:
                        continue
                    if remaining is not None:
                        remaining -= 1
                    summary = self._import_entry(state, entry, summary)
        return summary

    def _import_entry(
        self, state: StateStore, entry: FeedEntry, summary: ArchiveRunSummary
    ) -> ArchiveRunSummary:
        note: Path | None = None
        try:
            note = find_note_for_source(self._config.articles_path, entry.url)
            if note is not None:
                state.mark_imported(entry.subscription.feed_url, entry.url, str(note))
                return _with_summary(summary, recovered=summary.recovered + 1)

            imported_path = state.imported_output_path(entry.url)
            if imported_path is not None:
                state.mark_imported(entry.subscription.feed_url, entry.url, imported_path)
                return _with_summary(summary, recovered=summary.recovered + 1)

            state.begin_note_write(entry.subscription.feed_url, entry.url)
            article = self._defuddle(entry.url, self._config.defuddle_executable)
            note = create_note(
                self._config.articles_path,
                build_frontmatter(article, entry, datetime.now(timezone.utc)),
                article.markdown,
                entry.subscription.folder,
            )
            state.mark_imported(entry.subscription.feed_url, entry.url, str(note))
        except Exception as error:
            if note is None:
                try:
                    state.mark_failed(entry.subscription.feed_url, entry.url, str(error))
                except Exception as state_error:
                    self._logger.error("Failed to record archive failure %s: %s", entry.url, state_error)
            self._logger.error("Failed archive article %s: %s", entry.url, error)
            return _with_summary(summary, failed=summary.failed + 1)
        return _with_summary(summary, imported=summary.imported + 1)


def select_archive_sources(source: str) -> tuple[ArchiveSource, ...]:
    """Return archive sources in a stable order for the CLI source selector."""
    if source == "all":
        return tuple(ARCHIVE_SOURCES.values())
    return (ARCHIVE_SOURCES[source],)


def fetch_archive_bytes(url: str) -> bytes:
    """Fetch an archive page using the same explicit request policy as feeds."""
    request = Request(url, headers={"User-Agent": "opmlark/0.1"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def discover_bytebytego_urls(
    fetch_bytes: Callable[[str], bytes], *, years: Iterable[int] | None = None
) -> tuple[str, ...]:
    """Find public ByteByteGo post links from its yearly sitemap pages."""
    years = years if years is not None else range(2021, datetime.now(timezone.utc).year + 1)
    urls: list[str] = []
    for year in years:
        page_url = f"https://blog.bytebytego.com/sitemap/{year}"
        urls.extend(
            url
            for url in _html_links(fetch_bytes(page_url), page_url)
            if _is_hosted_path(url, "blog.bytebytego.com", "/p/")
        )
    return _unique_urls(urls)


def discover_highscalability_urls(fetch_bytes: Callable[[str], bytes]) -> tuple[str, ...]:
    """Find public High Scalability posts in its posts-only XML sitemap."""
    sitemap_url = "https://highscalability.com/sitemap-posts.xml"
    root = ElementTree.fromstring(fetch_bytes(sitemap_url))
    urls = (
        _canonical_url(element.text or "", sitemap_url)
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "loc"
    )
    return _unique_urls(
        url for url in urls if _is_hosted_path(url, "highscalability.com", "/")
    )


def discover_martin_kleppmann_urls(fetch_bytes: Callable[[str], bytes]) -> tuple[str, ...]:
    """Find dated post links in Martin Kleppmann's public archive page."""
    archive_url = "https://martin.kleppmann.com/archive.html"
    parser = _DatedArchiveParser(archive_url)
    parser.feed(fetch_bytes(archive_url).decode("utf-8", errors="replace"))
    parser.close()
    return _unique_urls(
        url
        for url in parser.urls
        if _is_hosted_path(url, "martin.kleppmann.com", "/")
        and urlsplit(url).path != "/archive.html"
    )


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.urls.append(_canonical_url(href, self._base_url))


class _DatedArchiveParser(_LinkParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url)
        self._list_depth = 0
        self._list_text: list[str] = []
        self._list_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self._list_depth += 1
            if self._list_depth == 1:
                self._list_text = []
                self._list_urls = []
            return
        if tag == "a" and self._list_depth:
            href = dict(attrs).get("href")
            if href:
                self._list_urls.append(_canonical_url(href, self._base_url))

    def handle_endtag(self, tag: str) -> None:
        if tag != "li" or not self._list_depth:
            return
        self._list_depth -= 1
        if self._list_depth == 0:
            if _contains_date("".join(self._list_text)):
                self.urls.extend(self._list_urls)
            self._list_text = []
            self._list_urls = []

    def handle_data(self, data: str) -> None:
        if self._list_depth:
            self._list_text.append(data)


def _html_links(contents: bytes, base_url: str) -> tuple[str, ...]:
    parser = _LinkParser(base_url)
    parser.feed(contents.decode("utf-8", errors="replace"))
    parser.close()
    return tuple(parser.urls)


def _contains_date(value: str) -> bool:
    return re.search(
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\b",
        value,
        re.IGNORECASE,
    ) is not None


def _canonical_url(value: str, base_url: str) -> str:
    parsed = urlsplit(urljoin(base_url, value.strip()))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _is_hosted_path(url: str, host: str, path_prefix: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname == host and parsed.path.startswith(path_prefix)


def _unique_urls(urls: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return tuple(unique)


def _with_summary(summary: ArchiveRunSummary, **changes: int) -> ArchiveRunSummary:
    return ArchiveRunSummary(
        discovered=changes.get("discovered", summary.discovered),
        pending=changes.get("pending", summary.pending),
        imported=changes.get("imported", summary.imported),
        recovered=changes.get("recovered", summary.recovered),
        failed=changes.get("failed", summary.failed),
        failed_sources=changes.get("failed_sources", summary.failed_sources),
    )
