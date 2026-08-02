from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class LibraryError(ValueError):
    """Raised when a collected article cannot be queried or read."""


@dataclass(frozen=True)
class ArticleRecord:
    url: str
    title: str
    published: str | None
    feed: str
    path: str


def list_articles(
    state_path: Path,
    *,
    feed: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> tuple[ArticleRecord, ...]:
    if limit <= 0:
        raise LibraryError("Article limit must be positive")
    normalized_since = _normalized_since(since)
    return _query_articles(state_path, feed=feed, since=normalized_since, limit=limit)


def _query_articles(
    state_path: Path,
    *,
    feed: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> tuple[ArticleRecord, ...]:
    if not state_path.is_file():
        return ()
    conditions = ["e.status = 'imported'", "e.output_path IS NOT NULL"]
    parameters: list[object] = []
    if feed:
        conditions.append("(e.feed_url = ? OR f.name = ?)")
        parameters.extend((feed, feed))
    if since:
        conditions.append("e.published >= ?")
        parameters.append(since)
    limit_clause = ""
    if limit is not None:
        parameters.append(limit)
        limit_clause = "LIMIT ?"
    connection = sqlite3.connect(f"{state_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return tuple(
            ArticleRecord(row[0], row[1] or "", row[2], row[3] or row[4], row[5])
            for row in connection.execute(
                f"""
                SELECT e.article_url, e.title, e.published, f.name, e.feed_url, e.output_path
                FROM entries e LEFT JOIN feeds f ON f.feed_url = e.feed_url
                WHERE {' AND '.join(conditions)}
                ORDER BY COALESCE(e.published, e.seen_at) DESC
                {limit_clause}
                """,
                parameters,
            )
        )
    finally:
        connection.close()


def read_article(state_path: Path, article_url: str) -> dict[str, str]:
    if not state_path.is_file():
        raise LibraryError("Workspace has no ingestion state yet")
    connection = sqlite3.connect(f"{state_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT output_path FROM entries
            WHERE article_url = ? AND status = 'imported' AND output_path IS NOT NULL
            LIMIT 1
            """,
            (article_url,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LibraryError(f"Imported article not found: {article_url}")
    path = Path(row[0])
    if not path.is_file():
        raise LibraryError(f"Article file is missing: {path}")
    return {"url": article_url, "path": str(path), "markdown": path.read_text(encoding="utf-8")}


def search_articles(
    state_path: Path, query: str, *, limit: int = 20
) -> tuple[dict[str, object], ...]:
    if not query.strip():
        raise LibraryError("Search query must be non-empty")
    needle = query.casefold()
    matches: list[dict[str, object]] = []
    for article in _query_articles(state_path):
        path = Path(article.path)
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        index = contents.casefold().find(needle)
        if index < 0:
            continue
        start = max(0, index - 100)
        end = min(len(contents), index + len(query) + 180)
        matches.append(
            {
                **asdict(article),
                "excerpt": " ".join(contents[start:end].split()),
            }
        )
        if len(matches) >= limit:
            break
    return tuple(matches)


def _normalized_since(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LibraryError("--since must be a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
