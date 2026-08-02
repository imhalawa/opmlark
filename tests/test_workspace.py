from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from article_importer.cli import main
from article_importer.configuration import load_config
from article_importer.scheduling import schedule_info
from article_importer.workspace import (
    WorkspaceError,
    add_category,
    add_catalog,
    add_feed,
    initialize_workspace,
    disable_catalog,
    list_catalogs,
    list_categories,
    list_feeds,
    remove_feed,
)


class WorkspaceTests(unittest.TestCase):
    def test_catalog_add_and_disable_preserve_opml_file(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            added = add_catalog(
                config, catalog_id="engineering", folder="Engineering"
            )
            disabled = disable_catalog(config, "engineering")

            self.assertTrue(Path(added.path).is_file())
            self.assertFalse(disabled.enabled)
            catalogs = {item.id: item for item in list_catalogs(config)}
            self.assertFalse(catalogs["engineering"].enabled)

    def test_init_creates_generic_markdown_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "library"

            created = initialize_workspace(root, "markdown/articles")
            config = load_config(Path(created["config"]))

            self.assertIsNone(config.vault_path)
            self.assertEqual(root / "markdown" / "articles", config.articles_path)
            self.assertEqual("reading", config.feed_catalogs[0].id)

    def test_category_and_feed_management_round_trip_through_opml(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            add_category(config, "reading", "Engineering/System Design")
            added = add_feed(
                config,
                catalog_id="reading",
                feed_id="example-engineering",
                name="Example Engineering",
                url="https://example.test/feed.xml",
                category="Engineering/System Design",
            )

            self.assertEqual("Engineering / System Design", list_feeds(config)[0].category)
            self.assertIn(
                {"catalog": "reading", "category": "Engineering / System Design"},
                list_categories(config),
            )
            self.assertEqual(added, remove_feed(config, "example-engineering"))
            self.assertEqual((), list_feeds(config))

    def test_duplicate_feed_id_is_rejected_across_catalog(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            details = dict(
                catalog_id="reading",
                feed_id="duplicate",
                name="Example",
                url="https://example.test/feed.xml",
                category="Reading",
            )
            add_feed(config, **details)

            with self.assertRaisesRegex(WorkspaceError, "already exists"):
                add_feed(config, **details)

    def test_cli_status_has_stable_json_output(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            output = StringIO()

            with redirect_stdout(output):
                result = main(["status", "--config", str(config), "--json"])

            self.assertEqual(0, result)
            self.assertIn('"feeds": 0', output.getvalue())
            self.assertIn('"imported": 0', output.getvalue())

    def test_schedule_show_uses_absolute_workspace_config(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            with patch("article_importer.scheduling.shutil.which", return_value="opmlark"):
                info = schedule_info(config, "06:30")

            self.assertEqual("06:30", info.time)
            self.assertIn(str(config.resolve()), info.command)


if __name__ == "__main__":
    unittest.main()
