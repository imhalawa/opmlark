from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch

from article_importer.tui import run_tui
from article_importer.workspace import initialize_workspace


class TuiTests(unittest.TestCase):
    def test_quit_returns_without_mutating_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(initialize_workspace(Path(directory))["config"])
            with (
                patch("article_importer.tui.find_config", return_value=config),
                patch("article_importer.tui.input", return_value="q"),
                patch("builtins.print"),
            ):
                result = run_tui()

            self.assertEqual(0, result)

    def test_menu_routes_catalog_and_article_operations(self) -> None:
        config = Path("C:/workspace/config.toml")
        with (
            patch("article_importer.tui.find_config", return_value=config),
            patch("article_importer.tui._print_status"),
            patch("article_importer.tui.input", side_effect=["6", "11", "q"]),
            patch("article_importer.tui.main", return_value=0) as main,
            patch("builtins.print"),
        ):
            result = run_tui()

        self.assertEqual(0, result)
        self.assertEqual(
            [
                call(["catalog", "list", "--config", str(config)]),
                call(
                    [
                        "article",
                        "list",
                        "--limit",
                        "50",
                        "--config",
                        str(config),
                    ]
                ),
            ],
            main.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
