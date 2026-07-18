from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FeedSubscription:
    topic: str
    name: str
    feed_url: str
    home_url: str | None = None


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published: datetime | None
    subscription: FeedSubscription
