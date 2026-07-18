from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

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


def create_note(articles_path: Path, frontmatter: str, markdown: str) -> Path:
    """Write a note once, choosing a numbered name if the title already exists."""
    title = _safe_title(_frontmatter_title(frontmatter))
    suffix_number = 1
    while True:
        suffix = "" if suffix_number == 1 else f" ({suffix_number})"
        name = f"Article - {title[: 140 - len(suffix)]}{suffix}.md"
        output = articles_path / name
        try:
            with output.open("x", encoding="utf-8", newline="") as note:
                note.write(frontmatter + markdown)
            return output
        except FileExistsError:
            suffix_number += 1


def find_note_for_source(articles_path: Path, source_url: str) -> Path | None:
    """Find an existing importer-created note for *source_url*, if one exists."""
    source_line = f"source: {_yaml_scalar(source_url)}"
    marker = "ingested_by: opml-defuddle-articles"
    for path in articles_path.glob("*.md"):
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if source_line in contents and marker in contents:
            return path
    return None


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
    match = re.search(r'^title: (.+)$', frontmatter, flags=re.MULTILINE)
    if not match:
        return "Untitled article"
    try:
        title = json.loads(match.group(1))
    except json.JSONDecodeError:
        return "Untitled article"
    return title if isinstance(title, str) else "Untitled article"


def _safe_title(title: str) -> str:
    safe = _WINDOWS_UNSAFE.sub("_", title)
    safe = _TRAILING_WINDOWS_UNSAFE.sub("_", safe).strip()
    return safe or "Untitled article"
