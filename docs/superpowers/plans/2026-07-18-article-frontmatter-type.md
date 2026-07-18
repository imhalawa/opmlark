# Article Frontmatter Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `type: article` to future importer notes and retrofit marked existing notes without altering bodies.

**Architecture:** Keep generated metadata in `article_importer.notes`. Add a small migration function there, and expose it through an explicit CLI flag in `fetch_articles.py` so normal imports remain unchanged.

**Tech Stack:** Python 3 standard library, unittest, Obsidian YAML frontmatter.

## Global Constraints

- Modify only YAML frontmatter of notes marked `ingested_by: opml-defuddle-articles`.
- Preserve article Markdown exactly.
- Use `type: article` as the exact property and value.

---

### Task 1: Generate and migrate the type property

**Files:**
- Modify: `article_importer/notes.py`
- Modify: `fetch_articles.py`
- Modify: `tests/test_notes.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Produces: `add_article_type_to_imported_notes(articles_path: Path) -> int`.
- Consumes: importer marker and the configured articles path.

- [ ] **Step 1: Write failing tests**

```python
self.assertIn('type: "article"\n', build_frontmatter(ARTICLE, ENTRY, NOW))
updated = add_article_type_to_imported_notes(self.articles)
self.assertEqual(1, updated)
self.assertEqual(original_body, note.read_text(encoding="utf-8").split("---\n", 2)[2])
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python -B -m unittest tests.test_notes -v`

Expected: failure because generated and migrated frontmatter omit `type: article`.

- [ ] **Step 3: Implement the minimal metadata and migration behavior**

```python
lines = ["---", 'type: "article"', f"title: {_yaml_scalar(title)}", ...]

def add_article_type_to_imported_notes(articles_path: Path) -> int:
    # Update only marker-bearing notes without a type key before the closing delimiter.
    ...
```

Add a `--add-article-type` flag that loads `config.toml`, calls the migration with `config.articles_path`, prints `updated=<count>`, and exits without fetching feeds.

- [ ] **Step 4: Run the focused tests to verify success**

Run: `python -B -m unittest tests.test_notes tests.test_service -v`

Expected: PASS.

- [ ] **Step 5: Run the migration and verify the result**

Run: `& .\run-import.ps1 --add-article-type`

Expected: a non-negative `updated` count; all marker-bearing notes include `type: article` and retain their original bodies.

- [ ] **Step 6: Run full verification and commit**

Run: `python -B -m unittest discover -s tests -v; git diff --check`

Expected: all tests pass and no whitespace errors.

```powershell
git add article_importer/notes.py fetch_articles.py tests/test_notes.py tests/test_service.py README.md
git commit -m "feat: classify imported article notes"
```
