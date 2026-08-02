from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from article_importer.cli import _parser, _schedule_from_args, main
from article_importer.configuration import Schedule, load_config
from article_importer.schedule_config import add_schedule_config
from article_importer.scheduling import ScheduleChange, schedule_info
from article_importer.workspace import (
    WorkspaceError,
    add_category,
    add_catalog,
    add_feed,
    initialize_workspace,
    disable_catalog,
    enable_catalog,
    list_catalogs,
    list_categories,
    list_feeds,
    remove_feed,
    remove_category,
    rename_category,
)


class WorkspaceTests(unittest.TestCase):
    def test_init_never_overwrites_an_existing_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = Path(initialize_workspace(root)["config"])
            original = config.read_bytes()

            with self.assertRaisesRegex(WorkspaceError, "already exists"):
                initialize_workspace(root)

            self.assertEqual(original, config.read_bytes())

    def test_catalog_rejects_paths_outside_workspace_before_writing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            config = Path(initialize_workspace(root)["config"])

            with self.assertRaisesRegex(WorkspaceError, "workspace-relative"):
                add_catalog(config, catalog_id="escape", path_value="../escape.opml")

            self.assertFalse((root.parent / "escape.opml").exists())

    def test_enabling_catalog_removes_legacy_global_disable(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "disabled_catalogs = []", 'disabled_catalogs = ["reading"]'
                ),
                encoding="utf-8",
            )

            enabled = enable_catalog(config, "reading")

            self.assertTrue(enabled.enabled)
            self.assertIn("disabled_catalogs = []", config.read_text(encoding="utf-8"))
            self.assertTrue(list_catalogs(config)[0].enabled)

    def test_catalog_add_and_disable_preserve_opml_file(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            added = add_catalog(
                config, catalog_id="engineering", folder="Engineering"
            )
            disabled = disable_catalog(config, "engineering")
            enabled = enable_catalog(config, "engineering")

            self.assertTrue(Path(added.path).is_file())
            self.assertFalse(disabled.enabled)
            catalogs = {item.id: item for item in list_catalogs(config)}
            self.assertTrue(enabled.enabled)
            self.assertTrue(catalogs["engineering"].enabled)

    def test_init_creates_generic_markdown_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            root = (Path(directory) / "library").resolve()

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
            rename_category(
                config, "reading", "Engineering/System Design", "Architecture"
            )
            remove_category(config, "reading", "Engineering/Architecture")
            remove_category(config, "reading", "Engineering")
            self.assertEqual((), list_categories(config))

    def test_nonempty_category_cannot_be_removed(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_feed(
                config,
                catalog_id="reading",
                feed_id="kept",
                name="Kept",
                url="https://example.test/feed.xml",
                category="Engineering",
            )

            with self.assertRaisesRegex(WorkspaceError, "empty category"):
                remove_category(config, "reading", "Engineering")

            self.assertEqual("kept", list_feeds(config)[0].id)

    def test_unicode_feed_metadata_round_trips_through_opml(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            add_feed(
                config,
                catalog_id="reading",
                feed_id="cafe-tech",
                name='Café & "Engineering"',
                url="https://example.test/feed?kind=one&lang=fr",
                category="Ingénierie/Échelle",
            )

            feed = list_feeds(config)[0]
            self.assertEqual('Café & "Engineering"', feed.name)
            self.assertEqual("Ingénierie / Échelle", feed.category)
            self.assertEqual("https://example.test/feed?kind=one&lang=fr", feed.url)

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

    def test_cli_errors_have_stable_json_shape(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            output = StringIO()

            with redirect_stdout(output):
                result = main(
                    [
                        "catalog",
                        "add",
                        "--config",
                        str(config),
                        "--id",
                        "INVALID ID",
                        "--json",
                    ]
                )

            self.assertEqual(1, result)
            self.assertIn('"ok": false', output.getvalue())
            self.assertIn('"error":', output.getvalue())

    def test_schedule_show_uses_absolute_workspace_config(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])

            with patch("article_importer.scheduling.shutil.which", return_value="opmlark"):
                info = schedule_info(config, "06:30")

            self.assertEqual("06:30", info.time)
            self.assertIn(str(config.resolve()), info.command)

    def test_cli_adds_every_portable_schedule_and_lists_json(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            commands = (
                ["morning", "--daily", "--at", "07:00"],
                ["weekend", "--weekly", "sat,sun", "--at", "09:30"],
                ["monthly-review", "--monthly", "15", "--at", "18:00"],
                ["special", "--once", "2026-09-15", "--at", "12:00"],
            )
            with patch(
                "article_importer.cli.apply_schedules",
                return_value=(ScheduleChange("item", "created"),),
            ):
                for values in commands:
                    self.assertEqual(
                        0,
                        main(["schedule", "add", *values, "--config", str(config), "--json"]),
                    )
            output = StringIO()
            with redirect_stdout(output):
                result = main(["schedule", "list", "--config", str(config), "--json"])

            self.assertEqual(0, result)
            self.assertEqual(
                {"morning", "weekend", "monthly-review", "special"},
                {item.id for item in load_config(config).schedules},
            )
            self.assertIn('"frequency": "weekly"', output.getvalue())

    def test_cli_edits_disables_enables_and_removes_by_id(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            with (
                patch(
                    "article_importer.cli.apply_schedules",
                    return_value=(ScheduleChange("morning", "updated"),),
                ),
                patch(
                    "article_importer.cli.remove_native_schedule",
                    return_value=ScheduleChange("morning", "removed"),
                ),
            ):
                self.assertEqual(0, main(["schedule", "edit", "morning", "--weekly", "mon,fri", "--at", "08:15", "--config", str(config)]))
                self.assertEqual(0, main(["schedule", "disable", "morning", "--config", str(config)]))
                self.assertFalse(load_config(config).schedules[0].enabled)
                self.assertEqual(0, main(["schedule", "enable", "morning", "--config", str(config)]))
                self.assertEqual(0, main(["schedule", "remove", "morning", "--config", str(config)]))

            self.assertEqual((), load_config(config).schedules)

    def test_cli_keeps_configuration_when_native_removal_fails(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("kept", "daily", "07:00"))
            with patch(
                "article_importer.cli.remove_native_schedule",
                return_value=ScheduleChange("kept", "failed", False, "denied"),
            ):
                result = main(["schedule", "remove", "kept", "--config", str(config)])

            self.assertEqual(1, result)
            self.assertEqual("kept", load_config(config).schedules[0].id)

    def test_interactive_schedule_add_prompts_for_recurrence_and_time(self) -> None:
        args = _parser().parse_args(["schedule", "add", "weekend"])
        with (
            patch("article_importer.cli.sys.stdin.isatty", return_value=True),
            patch("article_importer.cli.sys.stdout.isatty", return_value=True),
            patch("builtins.input", side_effect=["weekly", "sat,sun", "09:30"]) as prompt,
        ):
            schedule = _schedule_from_args(args)

        self.assertEqual(
            Schedule("weekend", "weekly", "09:30", days=("sat", "sun")),
            schedule,
        )
        self.assertEqual(3, prompt.call_count)

    def test_schedule_status_has_stable_json_output(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            output = StringIO()
            with (
                patch(
                    "article_importer.cli.schedule_status",
                    return_value=(ScheduleChange("morning", "missing"),),
                ),
                redirect_stdout(output),
            ):
                result = main(["schedule", "status", "--config", str(config), "--json"])

            self.assertEqual(0, result)
            self.assertIn('"id": "morning"', output.getvalue())
            self.assertIn('"action": "missing"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
