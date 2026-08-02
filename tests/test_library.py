from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from article_importer.library import list_articles, read_article, search_articles
from article_importer.models import FeedEntry, FeedSubscription
from article_importer.state import StateStore


class LibraryTests(unittest.TestCase):
    def test_list_search_and_read_use_imported_state_paths(self) -> None:
        subscription = FeedSubscription(
            "Engineering", "Example Engineering", "https://example.test/feed.xml"
        )
        entry = FeedEntry(
            "A distributed systems article",
            "https://example.test/article",
            None,
            subscription,
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "data" / "articles.sqlite3"
            article_path = root / "articles" / "article.md"
            article_path.parent.mkdir()
            article_path.write_text("# Article\n\nConsensus is contextual.\n", encoding="utf-8")
            with StateStore(state_path) as state:
                state.candidates(subscription, [entry])
                state.mark_imported(subscription.feed_url, entry.url, str(article_path))

            listed = list_articles(state_path)
            searched = search_articles(state_path, "consensus")
            read = read_article(state_path, entry.url)

            self.assertEqual(entry.url, listed[0].url)
            self.assertEqual(str(article_path), searched[0]["path"])
            self.assertIn("Consensus is contextual", read["markdown"])


if __name__ == "__main__":
    unittest.main()
