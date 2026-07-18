# Archive Blog Import Implementation Plan

**Goal:** Discover and import every currently public article from ByteByteGo, High Scalability, and Martin Kleppmann using Defuddle, with resumable SQLite deduplication.

## Global Constraints

- Write notes only through the existing frontmatter and note helpers; preserve Defuddle Markdown unchanged.
- Use the existing SQLite state outside the vault and avoid duplicates by article source URL, including legacy notes.
- Persistent feeds: ByteByteGo `https://blog.bytebytego.com/feed`, High Scalability `https://highscalability.com/rss/`, Martin Kleppmann `https://feeds.feedburner.com/martinkl`.
- Archive discovery: ByteByteGo yearly sitemap pages (2021 through current year); High Scalability `sitemap-posts.xml`; Martin Kleppmann `archive.html` dated post links.
- The archive command must be resumable, report counts, and never run from the normal daily job.

### Task 1: Archive discovery and import command

**Files:** `archive_articles.py`, `article_importer/archive.py`, `feeds.opml`, tests.

- [ ] Add deterministic discovery functions using `urllib` with a User-Agent, returning unique article URLs for each source.
- [ ] Reuse the configured Defuddle executable, generated frontmatter, atomic note creation, and SQLite status tracking. Treat already-existing notes with the same `source` URL as imported.
- [ ] Add `--source` (`bytebytego`, `highscalability`, `martin-kleppmann`, `all`) and `--limit` options. Default `all` and no limit imports all discovered URLs. Re-runs skip completed URLs and retry failures.
- [ ] Add the three feeds under System Design in OPML for ongoing daily imports.
- [ ] Test URL discovery parsing, source filtering, deduplication, and existing-source recovery without external network calls.
- [ ] Run an initial bounded command before launching the full resumable run.
