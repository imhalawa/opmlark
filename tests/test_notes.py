from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from article_importer.defuddle import DefuddledArticle, run_defuddle
from article_importer.models import FeedEntry, FeedSubscription
from article_importer.notes import build_frontmatter, create_note


NOW = datetime(2026, 7, 18, 7, 0, tzinfo=timezone.utc)
SUBSCRIPTION = FeedSubscription("System Design", "Publisher", "https://example.test/feed")
ENTRY = FeedEntry("Feed title", "https://example.test/article", NOW, SUBSCRIPTION)
ARTICLE = DefuddledArticle("A title", "Ada Lovelace", "## Original\n\nunchanged\n")


class NotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.articles = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("article_importer.defuddle.subprocess.run")
    def test_defuddle_returns_markdown_without_mutation(self, run: Mock) -> None:
        run.return_value = CompletedProcess(
            [],
            0,
            json.dumps({"title": "A title", "content": "## Original\n\nunchanged\n"}),
            "",
        )

        article = run_defuddle("https://example.test/article", "defuddle")

        self.assertEqual("## Original\n\nunchanged\n", article.markdown)
        self.assertEqual(
            ["defuddle", "parse", "https://example.test/article", "--json", "--md"],
            run.call_args.args[0],
        )
        self.assertEqual(
            {"capture_output": True, "text": True, "check": False, "timeout": 120},
            run.call_args.kwargs,
        )

    def test_note_has_marker_and_unchanged_body(self) -> None:
        body = "## Original\n\nunchanged\n"

        output = create_note(self.articles, build_frontmatter(ARTICLE, ENTRY, NOW), body)
        saved = output.read_text(encoding="utf-8")

        self.assertIn("ingested_by: opml-defuddle-articles\n", saved)
        self.assertTrue(saved.endswith(body))
        self.assertEqual(
            "---\n"
            'title: "A title"\n'
            'source: "https://example.test/article"\n'
            'feed: "Publisher"\n'
            'topic: "System Design"\n'
            'published: "2026-07-18T07:00:00+00:00"\n'
            'imported: "2026-07-18T07:00:00+00:00"\n'
            'author: "Ada Lovelace"\n'
            "ingested_by: opml-defuddle-articles\n"
            "tags:\n"
            "  - source/articles\n"
            "  - topic/system-design\n"
            "---\n",
            saved[: -len(body)],
        )

    def test_note_uses_incrementing_name_when_title_collides(self) -> None:
        frontmatter = build_frontmatter(ARTICLE, ENTRY, NOW)

        first = create_note(self.articles, frontmatter, ARTICLE.markdown)
        second = create_note(self.articles, frontmatter, ARTICLE.markdown)
        third = create_note(self.articles, frontmatter, ARTICLE.markdown)

        self.assertEqual("Article - A title.md", first.name)
        self.assertEqual("Article - A title (2).md", second.name)
        self.assertEqual("Article - A title (3).md", third.name)

    def test_note_name_sanitizes_windows_reserved_and_control_characters(self) -> None:
        article = DefuddledArticle('Bad<>:"/\\|?*\x00 title', None, "body")

        output = create_note(self.articles, build_frontmatter(article, ENTRY, NOW), article.markdown)

        self.assertEqual("Article - Bad__________ title.md", output.name)


if __name__ == "__main__":
    unittest.main()
