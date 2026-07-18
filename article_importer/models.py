from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class FeedSubscription:
    topic: str
    name: str
    feed_url: str
    home_url: str | None = None
    source_id: str | None = None
    folder: str | None = None


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published: datetime | None
    subscription: FeedSubscription
    publication_date_source: Literal["feed", "observed"] = "feed"
