from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from article_importer.cli import main
from article_importer.run_lock import RunLock
from article_importer.workspace import initialize_workspace


class RunLockTests(unittest.TestCase):
    def test_same_workspace_contends_then_reacquires_after_release(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "import.lock"
            with RunLock(path) as first:
                self.assertTrue(first.acquired)
                with RunLock(path) as second:
                    self.assertFalse(second.acquired)
            with RunLock(path) as third:
                self.assertTrue(third.acquired)

    def test_different_workspaces_do_not_contend(self) -> None:
        with TemporaryDirectory() as directory:
            first_path = Path(directory) / "one" / "import.lock"
            second_path = Path(directory) / "two" / "import.lock"
            with RunLock(first_path) as first, RunLock(second_path) as second:
                self.assertTrue(first.acquired)
                self.assertTrue(second.acquired)

    def test_cli_skips_an_overlapping_run_before_ingestion(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            output = StringIO()
            with RunLock(config.parent / "data" / "import.lock"):
                with redirect_stdout(output):
                    result = main(["run", "--config", str(config), "--json"])

            self.assertEqual(0, result)
            self.assertIn('"skipped": "already_running"', output.getvalue())
            self.assertFalse((config.parent / "data" / "articles.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
