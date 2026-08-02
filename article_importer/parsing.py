from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree

from article_importer.configuration import FeedCatalog
from article_importer.models import FeedEntry, FeedSubscription


class CatalogError(ValueError):
    """Raised when an enabled OPML catalog cannot be used safely."""


@dataclass(frozen=True)
class CatalogValidation:
    checked: int
    errors: tuple[str, ...] = ()


def parse_catalogs(
    catalogs: tuple[FeedCatalog, ...], *, disabled_sources: frozenset[str] = frozenset()
) -> list[FeedSubscription]:
    """Read enabled OPML catalogs and reject duplicate source identifiers."""
    subscriptions: list[FeedSubscription] = []
    source_ids: set[str] = set()
    for catalog in catalogs:
        if not catalog.enabled:
            continue
        for subscription in parse_opml(
            catalog.path,
            catalog_folder=catalog.folder,
            disabled_sources=disabled_sources,
        ):
            source_id = subscription.source_id
            if source_id in source_ids:
                raise CatalogError(f"duplicate enabled source id: {source_id}")
            source_ids.add(source_id)
            subscriptions.append(subscription)
    return subscriptions


def parse_opml(
    path: Path,
    *,
    catalog_folder: str | None = None,
    disabled_sources: frozenset[str] = frozenset(),
) -> list[FeedSubscription]:
    """Read enabled feed subscriptions from an OPML catalog."""
    root = ElementTree.parse(path).getroot()
    body = next((child for child in root if _local_name(child.tag) == "body"), None)
    if body is None:
        return []

    subscriptions: list[FeedSubscription] = []
    for outline in body:
        if _local_name(outline.tag) == "outline":
            _read_outline(
                outline,
                "",
                subscriptions,
                catalog_folder=catalog_folder,
                disabled_sources=disabled_sources,
            )
    return subscriptions


def validate_catalogs(
    catalogs: tuple[FeedCatalog, ...],
    *,
    disabled_sources: frozenset[str] = frozenset(),
) -> CatalogValidation:
    """Verify every enabled feed endpoint returns RSS or Atom XML."""
    subscriptions = parse_catalogs(catalogs, disabled_sources=disabled_sources)
    errors: list[str] = []
    for subscription in subscriptions:
        try:
            xml = _fetch_feed_bytes(subscription.feed_url)
            root = ElementTree.fromstring(xml)
            if _local_name(root.tag) not in {"rss", "feed"}:
                raise CatalogError("endpoint is not an RSS or Atom feed")
            parse_feed(xml, subscription)
        except Exception as error:
            errors.append(f"{subscription.source_id} ({subscription.feed_url}): {error}")
    return CatalogValidation(len(subscriptions), tuple(errors))


def _fetch_feed_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "opmlark/0.1"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def _read_outline(
    outline: ElementTree.Element,
    parent_topic: str,
    subscriptions: list[FeedSubscription],
    *,
    catalog_folder: str | None,
    disabled_sources: frozenset[str],
) -> None:
    if not _is_enabled(outline):
        return
    feed_url = outline.get("xmlUrl")
    if feed_url:
        source_id = (outline.get("id") or "").strip()
        if not source_id:
            raise CatalogError(f"feed {feed_url} is missing a stable id")
        if source_id in disabled_sources:
            return
        subscriptions.append(
            FeedSubscription(
                topic=parent_topic or "Uncategorized",
                name=outline.get("title") or outline.get("text", ""),
                feed_url=feed_url,
                home_url=outline.get("htmlUrl"),
                source_id=source_id,
                folder=outline.get("folder") or catalog_folder,
            )
        )
        return
    title = (outline.get("text") or "").strip()
    topic = " / ".join(part for part in (parent_topic, title) if part)
    for child in outline:
        if _local_name(child.tag) == "outline":
            _read_outline(
                child,
                topic,
                subscriptions,
                catalog_folder=catalog_folder,
                disabled_sources=disabled_sources,
            )


def _is_enabled(outline: ElementTree.Element) -> bool:
    return outline.get("enabled", "true").strip().lower() not in {"false", "0", "no"}


def parse_feed(xml: bytes, subscription: FeedSubscription) -> list[FeedEntry]:
    """Parse RSS or Atom XML into unique feed entries."""
    root = ElementTree.fromstring(xml)
    if _local_name(root.tag) == "rss":
        entries = _parse_rss(root, subscription)
    elif _local_name(root.tag) == "feed":
        entries = _parse_atom(root, subscription)
    else:
        entries = []

    unique_entries: list[FeedEntry] = []
    seen_urls: set[str] = set()
    for entry in entries:
        if entry.url and entry.url not in seen_urls:
            seen_urls.add(entry.url)
            unique_entries.append(entry)
    return unique_entries


def _parse_rss(root: ElementTree.Element, subscription: FeedSubscription) -> list[FeedEntry]:
    channel = next((child for child in root if _local_name(child.tag) == "channel"), None)
    if channel is None:
        return []

    entries: list[FeedEntry] = []
    for item in channel:
        if _local_name(item.tag) != "item":
            continue
        url = _resolved_text(item, "link", subscription.feed_url)
        if not url:
            continue
        entries.append(
            FeedEntry(
                title=_child_text(item, "title") or "",
                url=url,
                published=_parse_rss_date(_child_text(item, "pubDate")),
                subscription=subscription,
            )
        )
    return entries


def _parse_atom(root: ElementTree.Element, subscription: FeedSubscription) -> list[FeedEntry]:
    entries: list[FeedEntry] = []
    for item in root:
        if _local_name(item.tag) != "entry":
            continue
        url = _atom_url(item, subscription.feed_url)
        if not url:
            continue
        entries.append(
            FeedEntry(
                title=_child_text(item, "title") or "",
                url=url,
                published=_parse_atom_date(
                    _child_text(item, "published") or _child_text(item, "updated")
                ),
                subscription=subscription,
            )
        )
    return entries


def _atom_url(entry: ElementTree.Element, base_url: str) -> str | None:
    links = [child for child in entry if _local_name(child.tag) == "link"]
    alternate = next(
        (
            link
            for link in links
            if link.get("rel") == "alternate" and link.get("href", "").strip()
        ),
        None,
    )
    selected = alternate
    if selected is None:
        selected = next(
            (link for link in links if link.get("rel") is None and link.get("href")),
            None,
        )
    if selected is None:
        selected = next((link for link in links if link.get("href")), None)
    if selected is None:
        return None
    href = selected.get("href", "").strip()
    return urljoin(base_url, href) if href else None


def _resolved_text(element: ElementTree.Element, name: str, base_url: str) -> str | None:
    value = _child_text(element, name)
    return urljoin(base_url, value) if value else None


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    child = next((item for item in element if _local_name(item.tag) == name), None)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _parse_rss_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (IndexError, TypeError, ValueError):
        return None


def _parse_atom_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
