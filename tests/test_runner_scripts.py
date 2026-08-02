from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).parents[1]


class RunnerScriptTests(unittest.TestCase):
    def test_runner_adds_the_standard_npm_bin_for_defuddle(self) -> None:
        contents = (PROJECT_ROOT / "run-import.ps1").read_text(encoding="utf-8")

        self.assertIn("$env:APPDATA", contents)
        self.assertIn("defuddle.cmd", contents)

    @unittest.skipUnless(os.name == "nt", "PowerShell runner is Windows-specific")
    def test_runner_forwards_arguments_and_python_exit_code(self) -> None:
        runner = PROJECT_ROOT / "run-import.ps1"
        self.assertTrue(runner.exists(), "The project runner must exist")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy2(runner, root / runner.name)
            (root / "fetch_articles.py").write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "Path('arguments.txt').write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n"
                "raise SystemExit(23)\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-File", str(root / runner.name), "--dry-run", "extra"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(23, completed.returncode, completed.stderr)
            self.assertEqual("--dry-run\nextra", (root / "arguments.txt").read_text(encoding="utf-8"))


class ScheduledTaskScriptTests(unittest.TestCase):
    def test_scheduler_registers_the_required_daily_local_task(self) -> None:
        scheduler = PROJECT_ROOT / "install-scheduled-task.ps1"
        self.assertTrue(scheduler.exists(), "The scheduled-task installer must exist")

        contents = scheduler.read_text(encoding="utf-8")
        self.assertIn("Register-ScheduledTask -TaskName 'OPML Defuddle Articles'", contents)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At 7:00AM", contents)
        self.assertIn("run-import.ps1", contents)
        self.assertIn("-NoProfile -ExecutionPolicy Bypass -File", contents)
        self.assertIn("-StartWhenAvailable", contents)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Minutes 30)", contents)
        self.assertIn("-Force", contents)


class ReadmeTests(unittest.TestCase):
    def test_readme_documents_operation_and_cleanup(self) -> None:
        readme = PROJECT_ROOT / "README.md"
        self.assertTrue(readme.exists(), "The project README must exist")

        contents = readme.read_text(encoding="utf-8")
        for required_text in (
            "Prerequisites",
            "config.toml",
            "feeds/",
            "outline",
            "feed_catalogs",
            "--validate-catalogs",
            "lookback_days",
            "publication_date_source",
            "--dry-run",
            "run-import.ps1",
            "install-scheduled-task.ps1",
            "Unregister-ScheduledTask",
            "data/articles.sqlite3",
            "data/importer.log",
            "ingested_by: opml-defuddle-articles",
        ):
            self.assertIn(required_text, contents)


if __name__ == "__main__":
    unittest.main()
