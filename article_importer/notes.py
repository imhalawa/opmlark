from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from article_importer.defuddle import DefuddledArticle
from article_importer.models import FeedEntry


_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_TRAILING_WINDOWS_UNSAFE = re.compile(r"[. ]+$")
_FRONTMATTER_OPENING = re.compile(r"\A---(\r?\n)")
_FRONTMATTER_CLOSING = re.compile(r"^---(?:\r?\n|$)", re.MULTILINE)
_IMPORTER_MARKER = re.compile(
    r"^ingested_by:\s*opml-defuddle-articles\s*$", re.MULTILINE
)
_TYPE_FIELD = re.compile(r"^type\s*:", re.MULTILINE)
_ARTICLE_TYPE_FIELD = re.compile(r'^type\s*:\s*(?:"article"|article)\s*$', re.MULTILINE)
_TOPIC_FIELD = re.compile(r"^topic\s*:", re.MULTILINE)


def build_frontmatter(
    article: DefuddledArticle, entry: FeedEntry, imported_at: datetime
) -> str:
    """Build YAML frontmatter for a Defuddled article note."""
    title = article.title.strip() or entry.title.strip() or "Untitled article"
    lines = [
        "---",
        'type: "article"',
        f"title: {_yaml_scalar(title)}",
        f"source: {_yaml_scalar(entry.url)}",
        f"feed: {_yaml_scalar(entry.subscription.name)}",
        f"topic: {_yaml_scalar(entry.subscription.topic)}",
        f"published: {_yaml_scalar(_timestamp(entry.published))}",
        f"publication_date_source: {_yaml_scalar(entry.publication_date_source)}",
        f"imported: {_yaml_scalar(_timestamp(imported_at))}",
    ]
    if article.author:
        lines.append(f"author: {_yaml_scalar(article.author)}")
    lines.extend(
        [
            "ingested_by: opml-defuddle-articles",
            "tags:",
            "  - source/articles",
            f"  - topic/{_tag(entry.subscription.topic)}",
            "---",
        ]
    )
    return "\n".join(lines) + "\n"


def add_article_type_to_imported_notes(articles_path: Path) -> int:
    """Add the article type to importer-created notes that do not yet have one."""
    updated = 0
    for path in articles_path.glob("*.md"):
        try:
            with path.open("r", encoding="utf-8", newline="") as note:
                contents = note.read()
        except (OSError, UnicodeDecodeError):
            continue
        updated_contents = _add_article_type(contents)
        if updated_contents is None:
            continue
        _replace_atomically(path, updated_contents)
        updated += 1
    return updated


def add_topics_to_legacy_articles(articles_path: Path) -> int:
    """Classify legacy article notes that do not yet have a topic."""
    updated = 0
    for path in articles_path.glob("*.md"):
        try:
            with path.open("r", encoding="utf-8", newline="") as note:
                contents = note.read()
        except (OSError, UnicodeDecodeError):
            continue
        updated_contents = _add_legacy_topic(contents)
        if updated_contents is None:
            continue
        _replace_atomically(path, updated_contents)
        updated += 1
    return updated


def create_note(articles_path: Path, frontmatter: str, markdown: str) -> Path:
    """Write a note once, choosing a numbered name if the title already exists."""
    title = _safe_title(_frontmatter_title(frontmatter))
    folder = articles_path / source_folder_for_note(frontmatter)
    folder.mkdir(parents=True, exist_ok=True)
    suffix_number = 1
    while True:
        suffix = "" if suffix_number == 1 else f" ({suffix_number})"
        name = f"Article - {title[: 140 - len(suffix)]}{suffix}.md"
        output = folder / name
        try:
            with output.open("x", encoding="utf-8", newline="") as note:
                note.write(frontmatter + markdown)
            return output
        except FileExistsError:
            suffix_number += 1


def find_note_for_source(articles_path: Path, source_url: str) -> Path | None:
    """Find any existing article note whose frontmatter has *source_url*."""
    source_line = f"source: {_yaml_scalar(source_url)}"
    unquoted_source_line = f"source: {source_url}"
    for path in articles_path.rglob("*.md"):
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        opening = _FRONTMATTER_OPENING.match(contents)
        closing = _FRONTMATTER_CLOSING.search(contents, opening.end()) if opening else None
        if closing is None:
            continue
        frontmatter = contents[opening.end() : closing.start()]
        if any(
            line.strip() in {source_line, unquoted_source_line}
            for line in frontmatter.splitlines()
        ):
            return path
    return None


def source_folder_for_note(frontmatter: str) -> str:
    """Resolve an article's source folder from its existing frontmatter."""
    feed = _frontmatter_scalar(frontmatter, "feed")
    if feed:
        return _safe_folder_name(feed)
    source = _frontmatter_scalar(frontmatter, "source")
    hostname = urlsplit(source).hostname if source else None
    return _safe_folder_name(hostname) if hostname else "Unknown Source"


def group_articles_by_source(articles_path: Path, state_path: Path) -> int:
    """Move root-level article notes under source folders and repair state paths."""
    paths = tuple(path for path in articles_path.glob("*.md") if path.is_file())
    state = None
    if state_path.is_file():
        from article_importer.state import StateStore

        state = StateStore(state_path)
        state.__enter__()
    try:
        for path in paths:
            contents = path.read_text(encoding="utf-8")
            target_folder = articles_path / source_folder_for_note(_frontmatter_contents(contents))
            target_folder.mkdir(parents=True, exist_ok=True)
            target = _next_available_path(target_folder, path.name)
            path.replace(target)
            try:
                if state is not None:
                    state.update_output_path(str(path), str(target))
            except BaseException:
                target.replace(path)
                raise
    finally:
        if state is not None:
            state.__exit__(None, None, None)
    return len(paths)


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _add_article_type(contents: str) -> str | None:
    opening = _FRONTMATTER_OPENING.match(contents)
    if opening is None:
        return None
    closing = _FRONTMATTER_CLOSING.search(contents, opening.end())
    if closing is None:
        return None
    frontmatter = contents[opening.end() : closing.start()]
    if not _IMPORTER_MARKER.search(frontmatter) or _TYPE_FIELD.search(frontmatter):
        return None
    return contents[: opening.end()] + f'type: "article"{opening.group(1)}' + contents[opening.end() :]


def _add_legacy_topic(contents: str) -> str | None:
    opening = _FRONTMATTER_OPENING.match(contents)
    if opening is None:
        return None
    closing = _FRONTMATTER_CLOSING.search(contents, opening.end())
    if closing is None:
        return None
    frontmatter = contents[opening.end() : closing.start()]
    if _IMPORTER_MARKER.search(frontmatter) or _TOPIC_FIELD.search(frontmatter):
        return None
    if not _ARTICLE_TYPE_FIELD.search(frontmatter):
        return None
    topic = _legacy_topic(frontmatter)
    return contents[: opening.end()] + f"topic: {_yaml_scalar(topic)}{opening.group(1)}" + contents[opening.end() :]


def _legacy_topic(frontmatter: str) -> str:
    title = _frontmatter_title("---\n" + frontmatter + "---\n")
    tags = " ".join(re.findall(r"^\s{2}-\s+(.+)$", frontmatter, flags=re.MULTILINE))
    text = f"{title} {tags}".lower()
    if any(value in text for value in ("adhd", "procrastinat", "sleep", "focused", "time management")):
        return "Psychology (ADHD)"
    if any(value in text for value in ("sort", "algorithm", "data structure")):
        return "Algorithms and Data Structures"
    if any(value in text for value in ("aws", "system design", "distributed", "caching", "load balanc", "serverless", "domain-driven", "microservice", "nosql", "stack overflow")):
        return "System Design"
    if any(value in text for value in ("finance", "trading")):
        return "Finance"
    if any(value in text for value in ("universe", "physics", "multiverse")):
        return "Science"
    if any(value in text for value in ("questions", "better future", "pressure")):
        return "Personal Development"
    return "Software Engineering"


def _replace_atomically(path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _timestamp(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _tag(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "untagged"


def _frontmatter_title(frontmatter: str) -> str:
    title = _frontmatter_scalar(frontmatter, "title")
    return title or "Untitled article"


def _frontmatter_scalar(frontmatter: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    if match is None:
        return None
    try:
        title = json.loads(match.group(1))
    except json.JSONDecodeError:
        title = match.group(1).strip()
    return title if isinstance(title, str) and title else None


def _safe_title(title: str) -> str:
    safe = _WINDOWS_UNSAFE.sub("_", title)
    safe = _TRAILING_WINDOWS_UNSAFE.sub("_", safe).strip()
    return safe or "Untitled article"


def _safe_folder_name(name: str) -> str:
    safe = _WINDOWS_UNSAFE.sub("_", name)
    safe = _TRAILING_WINDOWS_UNSAFE.sub("_", safe).strip()
    return safe or "Unknown Source"


def _frontmatter_contents(contents: str) -> str:
    opening = _FRONTMATTER_OPENING.match(contents)
    if opening is None:
        return ""
    closing = _FRONTMATTER_CLOSING.search(contents, opening.end())
    return contents[opening.end() : closing.start()] if closing is not None else ""


def _next_available_path(folder: Path, name: str) -> Path:
    candidate = folder / name
    suffix_number = 2
    while candidate.exists():
        candidate = folder / f"{Path(name).stem} ({suffix_number}){Path(name).suffix}"
        suffix_number += 1
    return candidate
