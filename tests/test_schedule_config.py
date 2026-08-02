from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from article_importer.configuration import Schedule, load_config
from article_importer.schedule_config import (
    add_schedule_config,
    edit_schedule_config,
    list_schedule_config,
    remove_schedule_config,
    set_schedule_enabled,
)
from article_importer.workspace import WorkspaceError, initialize_workspace


class ScheduleConfigTests(unittest.TestCase):
    def test_mutations_round_trip_without_changing_other_configuration(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            original_catalog = '[[feed_catalogs]]\nid = "reading"\npath = "feeds/reading.opml"\nfolder = "Reading"'

            added = add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            add_schedule_config(
                config,
                Schedule("weekend", "weekly", "09:30", days=("sat", "sun")),
            )
            edited = edit_schedule_config(
                config,
                "morning",
                Schedule("morning", "monthly", "18:00", day=15),
            )
            disabled = set_schedule_enabled(config, "weekend", False)
            removed = remove_schedule_config(config, "morning")

            self.assertEqual("morning", added.id)
            self.assertEqual("monthly", edited.frequency)
            self.assertFalse(disabled.enabled)
            self.assertEqual("morning", removed.id)
            self.assertEqual((Schedule("weekend", "weekly", "09:30", False, ("sat", "sun")),), list_schedule_config(config))
            self.assertEqual(load_config(config).schedules, list_schedule_config(config))
            self.assertIn(original_catalog, config.read_text(encoding="utf-8"))

    def test_duplicate_unknown_and_renamed_ids_are_rejected_without_writes(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            add_schedule_config(config, Schedule("morning", "daily", "07:00"))
            original = config.read_bytes()

            operations = (
                lambda: add_schedule_config(config, Schedule("morning", "daily", "08:00")),
                lambda: edit_schedule_config(config, "missing", Schedule("missing", "daily", "08:00")),
                lambda: edit_schedule_config(config, "morning", Schedule("renamed", "daily", "08:00")),
                lambda: set_schedule_enabled(config, "missing", False),
                lambda: remove_schedule_config(config, "missing"),
            )
            for operation in operations:
                with self.subTest(operation=operation):
                    with self.assertRaises(WorkspaceError):
                        operation()
                    self.assertEqual(original, config.read_bytes())


if __name__ == "__main__":
    unittest.main()
