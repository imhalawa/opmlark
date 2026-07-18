from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ElementTree

from article_importer.models import FeedEntry, FeedSubscription


def parse_opml(path: Path) -> list[FeedSubscription]:
    """Read feed subscriptions from immediate OPML topic outlines."""
    root = ElementTree.parse(path).getroot()
    body = next((child for child in root if _local_name(child.tag) == "body"), None)
    if body is None:
        return []

    subscriptions: list[FeedSubscription] = []
    for topic_outline in body:
        if _local_name(topic_outline.tag) != "outline":
            continue
        topic = topic_outline.get("text", "")
        for feed_outline in topic_outline:
            if _local_name(feed_outline.tag) != "outline":
                continue
            feed_url = feed_outline.get("xmlUrl")
            if not feed_url:
                continue
            name = feed_outline.get("title") or feed_outline.get("text", "")
            subscriptions.append(
                FeedSubscription(
                    topic=topic,
                    name=name,
                    feed_url=feed_url,
                    home_url=feed_outline.get("htmlUrl"),
                )
            )
    return subscriptions


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
