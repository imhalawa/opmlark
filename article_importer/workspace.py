from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile
import tomllib
import xml.etree.ElementTree as ElementTree

from article_importer.configuration import FeedCatalog
from article_importer.notes import normalize_storage_folder
from article_importer.parsing import CatalogError, parse_catalogs
from article_importer.state import StateStore


class WorkspaceError(ValueError):
    """Raised when an OPMLark workspace operation is unsafe or ambiguous."""


@dataclass(frozen=True)
class CatalogInfo:
    id: str
    path: str
    folder: str | None
    enabled: bool


@dataclass(frozen=True)
class FeedInfo:
    id: str
    name: str
    url: str
    category: str
    catalog: str
    folder: str | None


def find_config(explicit: Path | None = None) -> Path:
    """Resolve a workspace configuration without depending on the package location."""
    if explicit is not None:
        path = explicit.expanduser().resolve()
    elif value := os.environ.get("OPMLARK_CONFIG"):
        path = Path(value).expanduser().resolve()
    else:
        path = (Path.cwd() / "config.toml").resolve()
    if not path.is_file():
        raise WorkspaceError(f"No OPMLark workspace found at {path}; run `opmlark init` first")
    return path


def initialize_workspace(root: Path, output: str = "articles") -> dict[str, str]:
    """Create a minimal, portable OPMLark workspace."""
    output = normalize_storage_folder(output)
    workspace = root.expanduser().resolve()
    config_path = workspace / "config.toml"
    feed_path = workspace / "feeds" / "reading.opml"
    output_path = workspace / output
    if config_path.exists():
        raise WorkspaceError(f"Workspace already exists: {config_path}")
    workspace.mkdir(parents=True, exist_ok=True)
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""[importer]
output_path = {json.dumps(output)}
defuddle_executable = \"defuddle\"
lookback_days = 90
max_attempts = 3

[feed_catalog]
disabled_catalogs = []
disabled_sources = []

[[feed_catalogs]]
id = \"reading\"
path = \"feeds/reading.opml\"
folder = \"Reading\"
""",
        encoding="utf-8",
    )
    feed_path.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<opml version="2.0">
  <head><title>OPMLark Reading</title></head>
  <body />
</opml>
""",
        encoding="utf-8",
    )
    return {
        "workspace": str(workspace),
        "config": str(config_path),
        "output": str(output_path),
        "catalog": str(feed_path),
    }


def list_catalogs(config_path: Path) -> tuple[CatalogInfo, ...]:
    return tuple(
        CatalogInfo(catalog.id, str(catalog.path), catalog.folder, catalog.enabled)
        for catalog in _catalogs(config_path, include_disabled=True)
    )


def add_catalog(
    config_path: Path,
    *,
    catalog_id: str,
    path_value: str | None = None,
    folder: str | None = None,
) -> CatalogInfo:
    if not catalog_id.strip() or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", catalog_id):
        raise WorkspaceError("Catalog id must use lowercase letters, numbers, and hyphens")
    if any(catalog.id == catalog_id for catalog in _catalogs(config_path, include_disabled=True)):
        raise WorkspaceError(f"Catalog id already exists: {catalog_id}")
    relative = Path((path_value or f"feeds/{catalog_id}.opml").replace("\\", "/"))
    if (
        relative.is_absolute()
        or relative.drive
        or ".." in relative.parts
        or relative.suffix.lower() != ".opml"
    ):
        raise WorkspaceError("Catalog path must be a workspace-relative .opml file")
    if folder is not None:
        normalize_storage_folder(folder)
    catalog_path = (config_path.parent / relative).resolve()
    if catalog_path.exists():
        raise WorkspaceError(f"Catalog file already exists: {catalog_path}")
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<opml version="2.0">
  <head><title>OPMLark Catalog</title></head>
  <body />
</opml>
""",
        encoding="utf-8",
    )
    block = (
        "\n[[feed_catalogs]]\n"
        f"id = {json.dumps(catalog_id)}\n"
        f"path = {json.dumps(relative.as_posix())}\n"
    )
    if folder:
        block += f"folder = {json.dumps(folder)}\n"
    try:
        _replace_text(config_path, config_path.read_text(encoding="utf-8").rstrip() + "\n" + block)
    except BaseException:
        catalog_path.unlink(missing_ok=True)
        raise
    return CatalogInfo(catalog_id, str(catalog_path), folder, True)


def disable_catalog(config_path: Path, catalog_id: str) -> CatalogInfo:
    matches = [
        catalog
        for catalog in _catalogs(config_path, include_disabled=True)
        if catalog.id == catalog_id
    ]
    if not matches:
        raise WorkspaceError(f"Unknown catalog: {catalog_id}")
    contents = config_path.read_text(encoding="utf-8")
    blocks = list(
        re.finditer(
            r"(?ms)^\[\[feed_catalogs\]\]\s*\n.*?(?=^\[\[feed_catalogs\]\]|\Z)",
            contents,
        )
    )
    for match in blocks:
        block = match.group(0)
        try:
            block_id = tomllib.loads(block)["feed_catalogs"][0]["id"]
        except (KeyError, IndexError, tomllib.TOMLDecodeError):
            continue
        if block_id == catalog_id:
            if re.search(r"(?m)^enabled\s*=", block):
                updated = re.sub(r"(?m)^enabled\s*=.*$", "enabled = false", block)
            else:
                updated = block.rstrip() + "\nenabled = false\n\n"
            _replace_text(config_path, contents[: match.start()] + updated + contents[match.end() :])
            catalog = matches[0]
            return CatalogInfo(catalog.id, str(catalog.path), catalog.folder, False)
    raise WorkspaceError(f"Unable to locate catalog configuration: {catalog_id}")


def list_feeds(config_path: Path) -> tuple[FeedInfo, ...]:
    catalogs = _catalogs(config_path)
    catalog_by_path = {catalog.path.resolve(): catalog.id for catalog in catalogs}
    results: list[FeedInfo] = []
    for catalog in catalogs:
        subscriptions = parse_catalogs((catalog,))
        for subscription in subscriptions:
            results.append(
                FeedInfo(
                    subscription.source_id or "",
                    subscription.name,
                    subscription.feed_url,
                    subscription.topic,
                    catalog_by_path[catalog.path.resolve()],
                    subscription.folder,
                )
            )
    return tuple(results)


def list_categories(config_path: Path, catalog_id: str | None = None) -> tuple[dict[str, str], ...]:
    results: list[dict[str, str]] = []
    for catalog in _selected_catalogs(config_path, catalog_id):
        root = ElementTree.parse(catalog.path).getroot()
        body = next((item for item in root if _local_name(item.tag) == "body"), None)
        if body is not None:
            _collect_categories(body, "", catalog.id, results)
    return tuple(results)


def add_category(config_path: Path, catalog_id: str, category: str) -> dict[str, str]:
    catalog = _one_catalog(config_path, catalog_id)
    tree = ElementTree.parse(catalog.path)
    body = _body(tree)
    _category_node(body, category, create=True)
    _write_opml(tree, catalog.path)
    return {"catalog": catalog.id, "category": category}


def add_feed(
    config_path: Path,
    *,
    catalog_id: str,
    feed_id: str,
    name: str,
    url: str,
    category: str,
    home_url: str | None = None,
    folder: str | None = None,
) -> FeedInfo:
    if not feed_id.strip() or not name.strip() or not url.strip():
        raise WorkspaceError("Feed id, name, and URL must be non-empty")
    if any(feed.id == feed_id for feed in list_feeds(config_path)):
        raise WorkspaceError(f"Feed id already exists: {feed_id}")
    if folder is not None:
        normalize_storage_folder(folder)
    canonical_category = " / ".join(part.strip() for part in category.split("/") if part.strip())
    catalog = _one_catalog(config_path, catalog_id)
    tree = ElementTree.parse(catalog.path)
    parent = _category_node(_body(tree), category, create=True)
    attributes = {"id": feed_id, "text": name, "title": name, "xmlUrl": url}
    if home_url:
        attributes["htmlUrl"] = home_url
    if folder:
        attributes["folder"] = folder
    ElementTree.SubElement(parent, "outline", attributes)
    _write_opml(tree, catalog.path)
    return FeedInfo(
        feed_id, name, url, canonical_category, catalog_id, folder or catalog.folder
    )


def remove_feed(config_path: Path, feed_id: str) -> FeedInfo:
    matches = [feed for feed in list_feeds(config_path) if feed.id == feed_id]
    if not matches:
        raise WorkspaceError(f"Unknown feed id: {feed_id}")
    feed = matches[0]
    catalog = _one_catalog(config_path, feed.catalog)
    tree = ElementTree.parse(catalog.path)
    body = _body(tree)
    if not _remove_outline(body, feed_id):
        raise WorkspaceError(f"Unable to remove feed id: {feed_id}")
    _write_opml(tree, catalog.path)
    return feed


def workspace_status(config_path: Path) -> dict[str, object]:
    state_path = config_path.parent / "data" / "articles.sqlite3"
    counts = {"seeded": 0, "imported": 0, "failed": 0}
    if state_path.is_file():
        connection = sqlite3.connect(f"{state_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            for status, count in connection.execute(
                "SELECT status, count(*) FROM entries GROUP BY status"
            ):
                if status in counts:
                    counts[status] = count
        finally:
            connection.close()
    return {
        "config": str(config_path),
        "catalogs": len(list_catalogs(config_path)),
        "feeds": len(list_feeds(config_path)),
        "articles": counts,
    }


def list_failures(config_path: Path) -> tuple[dict[str, object], ...]:
    state_path = config_path.parent / "data" / "articles.sqlite3"
    if not state_path.is_file():
        return ()
    with StateStore(state_path) as state:
        return state.failures()


def retry_failure(config_path: Path, article_url: str) -> dict[str, str]:
    state_path = config_path.parent / "data" / "articles.sqlite3"
    if not state_path.is_file():
        raise WorkspaceError("Workspace has no ingestion state yet")
    with StateStore(state_path) as state:
        if not state.reset_failure(article_url):
            raise WorkspaceError(f"No failed article found: {article_url}")
    return {"url": article_url, "status": "ready_to_retry"}


def to_json(value: object) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    elif isinstance(value, tuple):
        value = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
    return json.dumps(value, ensure_ascii=False, indent=2)


def _catalogs(config_path: Path, include_disabled: bool = False) -> tuple[FeedCatalog, ...]:
    try:
        with config_path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise WorkspaceError(f"Unable to read workspace configuration: {error}") from error
    values = document.get("feed_catalogs", [])
    if not isinstance(values, list):
        raise WorkspaceError("feed_catalogs must be an array of tables")
    disabled = document.get("feed_catalog", {}).get("disabled_catalogs", [])
    results: list[FeedCatalog] = []
    for value in values:
        if not isinstance(value, dict):
            raise WorkspaceError("each feed catalog must be a table")
        catalog_id = value.get("id")
        path_value = value.get("path")
        enabled = value.get("enabled", True) and catalog_id not in disabled
        if not isinstance(catalog_id, str) or not isinstance(path_value, str):
            raise WorkspaceError("each feed catalog needs string id and path values")
        if include_disabled or enabled:
            path = Path(path_value)
            if not path.is_absolute():
                path = (config_path.parent / path).resolve()
            results.append(FeedCatalog(catalog_id, path, bool(enabled), value.get("folder")))
    return tuple(results)


def _selected_catalogs(config_path: Path, catalog_id: str | None) -> tuple[FeedCatalog, ...]:
    catalogs = _catalogs(config_path)
    if catalog_id is None:
        return catalogs
    return (_one_catalog(config_path, catalog_id),)


def _one_catalog(config_path: Path, catalog_id: str) -> FeedCatalog:
    matches = [catalog for catalog in _catalogs(config_path) if catalog.id == catalog_id]
    if not matches:
        raise WorkspaceError(f"Unknown enabled catalog: {catalog_id}")
    return matches[0]


def _body(tree: ElementTree.ElementTree) -> ElementTree.Element:
    root = tree.getroot()
    body = next((item for item in root if _local_name(item.tag) == "body"), None)
    if body is None:
        raise WorkspaceError("OPML catalog has no body")
    return body


def _category_node(parent: ElementTree.Element, category: str, *, create: bool) -> ElementTree.Element:
    current = parent
    for part in (item.strip() for item in category.split("/")):
        if not part:
            raise WorkspaceError("Category must contain non-empty slash-separated names")
        match = next(
            (
                child
                for child in current
                if _local_name(child.tag) == "outline"
                and child.get("xmlUrl") is None
                and (child.get("text") or "").strip() == part
            ),
            None,
        )
        if match is None:
            if not create:
                raise WorkspaceError(f"Unknown category: {category}")
            match = ElementTree.SubElement(current, "outline", {"text": part})
        current = match
    return current


def _collect_categories(
    parent: ElementTree.Element, prefix: str, catalog_id: str, results: list[dict[str, str]]
) -> None:
    for child in parent:
        if _local_name(child.tag) != "outline" or child.get("xmlUrl"):
            continue
        name = (child.get("text") or "").strip()
        if not name:
            continue
        category = " / ".join(part for part in (prefix, name) if part)
        results.append({"catalog": catalog_id, "category": category})
        _collect_categories(child, category, catalog_id, results)


def _remove_outline(parent: ElementTree.Element, feed_id: str) -> bool:
    for child in list(parent):
        if child.get("xmlUrl") and (child.get("id") or "").strip() == feed_id:
            parent.remove(child)
            return True
        if _remove_outline(child, feed_id):
            return True
    return False


def _write_opml(tree: ElementTree.ElementTree, path: Path) -> None:
    ElementTree.indent(tree, space="  ")
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temporary:
            tree.write(temporary, encoding="utf-8", xml_declaration=True)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _replace_text(path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as temporary:
            temporary.write(contents)
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
