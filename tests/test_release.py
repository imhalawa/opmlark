from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from article_importer import __version__


ROOT = Path(__file__).parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_package_versions_match(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        with (ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]

        self.assertEqual(__version__, package["version"])
        self.assertEqual(__version__, project["version"])

    def test_release_workflow_is_retry_safe(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("gh release view", workflow)
        self.assertIn("npm view", workflow)


if __name__ == "__main__":
    unittest.main()
