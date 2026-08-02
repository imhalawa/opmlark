from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from article_importer.scheduling import (
    ScheduleInfo,
    install_schedule,
    schedule_info,
)
from article_importer.workspace import WorkspaceError


class SchedulingTests(unittest.TestCase):
    def test_windows_npm_shim_runs_through_command_processor(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.touch()
            with (
                patch(
                    "article_importer.scheduling.shutil.which",
                    return_value=r"C:\Program Files\nodejs\opmlark.cmd",
                ),
                patch("article_importer.scheduling._is_windows", return_value=True),
            ):
                info = schedule_info(config)

            self.assertTrue(info.command.startswith('cmd.exe /D /C ""'))
            self.assertIn("opmlark.cmd", info.command)

    def test_temporary_npx_command_is_rejected_for_schedule(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.touch()
            with patch(
                "article_importer.scheduling.shutil.which",
                return_value=r"C:\cache\_npx\123\opmlark.cmd",
            ):
                with self.assertRaisesRegex(WorkspaceError, "temporary npx"):
                    schedule_info(config)

    def test_cron_install_creates_log_directory_and_replaces_its_entry(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.touch()
            info = ScheduleInfo("cron", "OPMLark test", "07:00", "opmlark run")
            with (
                patch("article_importer.scheduling.schedule_info", return_value=info),
                patch("article_importer.scheduling._is_windows", return_value=False),
                patch(
                    "article_importer.scheduling._read_crontab",
                    return_value="0 7 * * * old # opmlark:unrelated\n",
                ),
                patch("article_importer.scheduling._write_crontab") as write,
            ):
                installed = install_schedule(config)

            self.assertEqual(info, installed)
            self.assertTrue((config.parent / "data").is_dir())
            contents = write.call_args.args[0]
            self.assertIn("scheduler.log", contents)
            self.assertIn("# opmlark:", contents)
            self.assertIn("# opmlark:unrelated", contents)

    def test_same_named_workspaces_get_distinct_task_names(self) -> None:
        with TemporaryDirectory() as directory:
            first = Path(directory) / "one" / "reading" / "config.toml"
            second = Path(directory) / "two" / "reading" / "config.toml"
            with patch("article_importer.scheduling.shutil.which", return_value="opmlark"):
                first_info = schedule_info(first)
                second_info = schedule_info(second)

            self.assertNotEqual(first_info.name, second_info.name)


if __name__ == "__main__":
    unittest.main()
