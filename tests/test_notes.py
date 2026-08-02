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
from article_importer.notes import (
    add_article_type_to_imported_notes,
    add_topics_to_legacy_articles,
    build_frontmatter,
    create_note,
    group_articles_by_source,
    normalize_storage_folder,
    source_folder_for_note,
)
from article_importer.state import StateStore


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

    @patch("article_importer.defuddle.subprocess.run")
    @patch("shutil.which", return_value="C:/tools/node.exe")
    def test_defuddle_cmd_shim_uses_node_without_a_batch_shell(
        self, which: Mock, run: Mock
    ) -> None:
        run.return_value = CompletedProcess(
            [],
            0,
            json.dumps({"title": "A title", "content": "body"}),
            "",
        )
        shim = self.articles / "defuddle.cmd"
        cli = shim.parent / "node_modules" / "defuddle" / "dist" / "cli.js"
        cli.parent.mkdir(parents=True)
        cli.touch()

        run_defuddle("https://example.test/article?tag=a&tag=b", str(shim))

        self.assertEqual(
            [
                "C:/tools/node.exe",
                str(cli),
                "parse",
                "https://example.test/article?tag=a&tag=b",
                "--json",
                "--md",
            ],
            run.call_args.args[0],
        )
        which.assert_called_once_with("node")

    @patch("article_importer.defuddle.subprocess.run")
    @patch("shutil.which", return_value="C:/tools/node.exe")
    def test_defuddle_local_cmd_shim_finds_its_package_cli(self, which: Mock, run: Mock) -> None:
        run.return_value = CompletedProcess(
            [],
            0,
            json.dumps({"title": "A title", "content": "body"}),
            "",
        )
        shim = self.articles / "node_modules" / ".bin" / "defuddle.cmd"
        cli = self.articles / "node_modules" / "defuddle" / "dist" / "cli.js"
        cli.parent.mkdir(parents=True)
        cli.touch()

        run_defuddle("https://example.test/article", str(shim))

        self.assertEqual(
            [
                "C:/tools/node.exe",
                str(cli),
                "parse",
                "https://example.test/article",
                "--json",
                "--md",
            ],
            run.call_args.args[0],
        )
        which.assert_called_once_with("node")

    @patch("article_importer.defuddle.subprocess.run")
    @patch("shutil.which", return_value="C:/tools/node.exe")
    def test_defuddle_cmd_shim_prefers_a_sibling_node_runtime(
        self, which: Mock, run: Mock
    ) -> None:
        run.return_value = CompletedProcess(
            [],
            0,
            json.dumps({"title": "A title", "content": "body"}),
            "",
        )
        shim = self.articles / "defuddle.cmd"
        node = shim.with_name("node.exe")
        cli = shim.parent / "node_modules" / "defuddle" / "dist" / "cli.js"
        cli.parent.mkdir(parents=True)
        cli.touch()
        node.touch()

        run_defuddle("https://example.test/article", str(shim))

        self.assertEqual(str(node), run.call_args.args[0][0])
        which.assert_not_called()

    def test_note_has_marker_and_unchanged_body(self) -> None:
        body = "## Original\n\nunchanged\n"

        output = create_note(self.articles, build_frontmatter(ARTICLE, ENTRY, NOW), body)
        saved = output.read_text(encoding="utf-8")

        self.assertIn("ingested_by: opmlark\n", saved)
        self.assertTrue(saved.endswith(body))
        self.assertEqual(
            "---\n"
            'type: "article"\n'
            'title: "A title"\n'
            'source: "https://example.test/article"\n'
            'feed: "Publisher"\n'
            'topic: "System Design"\n'
            'published: "2026-07-18T07:00:00+00:00"\n'
            'publication_date_source: "feed"\n'
            'imported: "2026-07-18T07:00:00+00:00"\n'
            'author: "Ada Lovelace"\n'
            "ingested_by: opmlark\n"
            "tags:\n"
            "  - source/articles\n"
            "  - topic/system-design\n"
            "---\n",
            saved[: -len(body)],
        )

    def test_source_folder_uses_feed_then_source_hostname_then_unknown(self) -> None:
        self.assertEqual("ByteByteGo", source_folder_for_note('feed: "ByteByteGo"'))
        self.assertEqual(
            "stephango.com",
            source_folder_for_note('source: "https://stephango.com/post"'),
        )
        self.assertEqual("Unknown Source", source_folder_for_note("title: Missing"))

    def test_source_folder_prefers_explicit_storage_folder(self) -> None:
        self.assertEqual(
            "Company Engineering/Uber",
            source_folder_for_note('feed: "Uber Engineering"', "Company Engineering/Uber"),
        )

    def test_storage_folder_rejects_absolute_and_traversal_paths(self) -> None:
        for value in ("", "/outside", "C:/outside", "../outside", "Team/../outside", "Team//Uber"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_storage_folder(value)

    def test_note_is_created_in_its_feed_source_folder(self) -> None:
        output = create_note(
            self.articles, build_frontmatter(ARTICLE, ENTRY, NOW), ARTICLE.markdown
        )

        self.assertEqual(self.articles / "Publisher" / "Article - A title.md", output)

    def test_note_is_created_in_explicit_nested_storage_folder(self) -> None:
        subscription = FeedSubscription(
            "System Design",
            "Uber Engineering",
            "https://example.test/feed",
            source_id="uber-engineering",
            folder="Company Engineering/Uber",
        )
        entry = FeedEntry("Feed title", "https://example.test/article", NOW, subscription)

        output = create_note(
            self.articles, build_frontmatter(ARTICLE, entry, NOW), ARTICLE.markdown, subscription.folder
        )

        self.assertEqual(
            self.articles / "Company Engineering" / "Uber" / "Article - A title.md", output
        )

    def test_group_articles_moves_root_note_without_changing_bytes_or_losing_state(self) -> None:
        note = self.articles / "legacy.md"
        original_bytes = (
            b'---\nfeed: "Publisher"\nsource: "https://example.test/article"\n---\n'
            b"# Exact article body\n"
        )
        note.write_bytes(original_bytes)
        state_path = self.articles.parent / "data" / "articles.sqlite3"
        with StateStore(state_path) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            state.mark_imported(SUBSCRIPTION.feed_url, ENTRY.url, str(note))

        updated = group_articles_by_source(self.articles, state_path)
        moved_path = self.articles / "Publisher" / note.name
        with StateStore(state_path) as state:
            stored_output_path = state.imported_output_path(ENTRY.url)

        self.assertEqual(1, updated)
        self.assertEqual(original_bytes, moved_path.read_bytes())
        self.assertEqual(str(moved_path), stored_output_path)

    def test_group_articles_uses_a_numbered_name_for_a_collision(self) -> None:
        note = self.articles / "legacy.md"
        note.write_text('---\nfeed: "Publisher"\n---\nbody\n', encoding="utf-8")
        target = self.articles / "Publisher"
        target.mkdir()
        (target / note.name).write_text("existing\n", encoding="utf-8")

        updated = group_articles_by_source(self.articles, self.articles / "missing.sqlite3")

        self.assertEqual(1, updated)
        self.assertTrue((target / "legacy (2).md").is_file())

    def test_group_articles_restores_note_when_state_path_update_fails(self) -> None:
        note = self.articles / "legacy.md"
        original_bytes = b'---\nfeed: "Publisher"\n---\n# Exact article body\n'
        note.write_bytes(original_bytes)
        state_path = self.articles.parent / "data" / "articles.sqlite3"
        with StateStore(state_path) as state:
            state.candidates(SUBSCRIPTION, [ENTRY])
            state.mark_imported(SUBSCRIPTION.feed_url, ENTRY.url, str(note))

        with patch(
            "article_importer.state.StateStore.update_output_path",
            side_effect=OSError("database is unavailable"),
        ):
            with self.assertRaisesRegex(OSError, "database is unavailable"):
                group_articles_by_source(self.articles, state_path)

        self.assertEqual(original_bytes, note.read_bytes())
        self.assertFalse((self.articles / "Publisher" / note.name).exists())

    def test_add_article_type_updates_only_marked_notes_without_a_type(self) -> None:
        note = self.articles / "Article - imported.md"
        original_body = "## Original\n\nunchanged\n"
        note.write_text(
            "---\n"
            'title: "Imported"\n'
            "ingested_by: opml-defuddle-articles\n"
            "---\n"
            + original_body,
            encoding="utf-8",
            newline="",
        )
        (self.articles / "ordinary.md").write_text(
            "---\n"
            'title: "Ordinary"\n'
            "---\n"
            "untouched\n",
            encoding="utf-8",
            newline="",
        )
        typed_note = self.articles / "Article - typed.md"
        typed_note.write_text(
            "---\n"
            'type: "article"\n'
            "ingested_by: opml-defuddle-articles\n"
            "---\n"
            "already typed\n",
            encoding="utf-8",
            newline="",
        )

        updated = add_article_type_to_imported_notes(self.articles)

        self.assertEqual(1, updated)
        saved = note.read_text(encoding="utf-8")
        self.assertIn('type: "article"\n', saved)
        self.assertEqual(original_body, saved.split("---\n", 2)[2])
        self.assertNotIn('type: "article"', (self.articles / "ordinary.md").read_text(encoding="utf-8"))
        self.assertEqual(
            "already typed\n", typed_note.read_text(encoding="utf-8").split("---\n", 2)[2]
        )

    def test_add_article_type_is_idempotent(self) -> None:
        note = self.articles / "Article - imported.md"
        note.write_text(
            "---\n"
            "ingested_by: opml-defuddle-articles\n"
            "---\n"
            "body\n",
            encoding="utf-8",
            newline="",
        )

        add_article_type_to_imported_notes(self.articles)
        contents_after_first_run = note.read_bytes()

        self.assertEqual(0, add_article_type_to_imported_notes(self.articles))
        self.assertEqual(contents_after_first_run, note.read_bytes())

    @patch("article_importer.notes.Path.replace", side_effect=OSError("disk full"))
    def test_add_article_type_keeps_original_note_when_atomic_replace_fails(self, replace: Mock) -> None:
        note = self.articles / "Article - imported.md"
        original = (
            "---\n"
            "ingested_by: opml-defuddle-articles\n"
            "---\n"
            "body\n"
        ).encode()
        note.write_bytes(original)

        with self.assertRaisesRegex(OSError, "disk full"):
            add_article_type_to_imported_notes(self.articles)

        self.assertEqual(original, note.read_bytes())
        replace.assert_called_once()

    def test_add_topics_classifies_legacy_notes_without_overwriting_topics(self) -> None:
        system_design = self.articles / "system-design.md"
        system_design.write_text(
            "---\n"
            'title: "Caching Strategies"\n'
            "tags:\n"
            "  - aws\n"
            "type: article\n"
            "---\n"
            "body\n",
            encoding="utf-8",
            newline="",
        )
        algorithms = self.articles / "algorithms.md"
        algorithms.write_text(
            "---\n"
            'title: "Counting and Bucket Sort"\n'
            "type: article\n"
            "---\n"
            "algorithm body\n",
            encoding="utf-8",
            newline="",
        )
        preserved = self.articles / "preserved.md"
        preserved.write_text(
            "---\n"
            'title: "Existing"\n'
            'topic: "Custom"\n'
            "type: article\n"
            "---\n"
            "body\n",
            encoding="utf-8",
            newline="",
        )
        non_article = self.articles / "book.md"
        non_article.write_text(
            "---\n"
            'title: "A Book"\n'
            "type: book\n"
            "---\n"
            "body\n",
            encoding="utf-8",
            newline="",
        )

        updated = add_topics_to_legacy_articles(self.articles)

        self.assertEqual(2, updated)
        self.assertIn('topic: "System Design"\n', system_design.read_text(encoding="utf-8"))
        self.assertIn(
            'topic: "Algorithms and Data Structures"\n', algorithms.read_text(encoding="utf-8")
        )
        self.assertIn('topic: "Custom"\n', preserved.read_text(encoding="utf-8"))
        self.assertNotIn('topic:', non_article.read_text(encoding="utf-8"))

    def test_note_uses_incrementing_name_when_title_collides(self) -> None:
        frontmatter = build_frontmatter(ARTICLE, ENTRY, NOW)

        first = create_note(self.articles, frontmatter, ARTICLE.markdown)
        second = create_note(self.articles, frontmatter, ARTICLE.markdown)
        third = create_note(self.articles, frontmatter, ARTICLE.markdown)

        self.assertEqual("Article - A title.md", first.name)
        self.assertEqual("Article - A title (2).md", second.name)
        self.assertEqual("Article - A title (3).md", third.name)

    def test_observed_date_provenance_is_written_to_frontmatter(self) -> None:
        observed_entry = FeedEntry(
            "Undated feed title",
            "https://example.test/undated",
            NOW,
            SUBSCRIPTION,
            "observed",
        )

        frontmatter = build_frontmatter(ARTICLE, observed_entry, NOW)

        self.assertIn('publication_date_source: "observed"', frontmatter)

    def test_note_name_sanitizes_windows_reserved_and_control_characters(self) -> None:
        article = DefuddledArticle('Bad<>:"/\\|?*\x00 title', None, "body")

        output = create_note(self.articles, build_frontmatter(article, ENTRY, NOW), article.markdown)

        self.assertEqual("Article - Bad__________ title.md", output.name)


if __name__ == "__main__":
    unittest.main()
