# Group Articles by Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all article notes into source-named folders and write future imports there.

**Architecture:** Centralize frontmatter-based source-folder resolution and move logic in `article_importer.notes`. Expose an explicit migration command that updates SQLite output paths after each successful move; callers pause the archive worker before running it.

**Tech Stack:** Python 3 standard library, SQLite, unittest, Obsidian Markdown.

## Global Constraints

- Importer notes use `feed`; legacy notes use the hostname from `source`; unresolved notes use `Unknown Source`.
- Move only Markdown notes directly below `Sources/Articles`.
- Preserve each note byte-for-byte and never overwrite an existing filename.
- Update SQLite output paths after successful moves.
- Future notes are created directly in their resolved source folder.

---

### Task 1: Source-folder resolution and future note placement

**Files:**
- Modify: `article_importer/notes.py`
- Modify: `article_importer/service.py`, `article_importer/archive.py`
- Modify: `tests/test_notes.py`, `tests/test_service.py`, `tests/test_archive.py`

**Interfaces:**
- Produces: `source_folder_for_note(frontmatter: str) -> str` and folder-aware `create_note` calls.

- [ ] **Step 1: Write failing tests**

```python
self.assertEqual("ByteByteGo", source_folder_for_note('feed: "ByteByteGo"'))
self.assertEqual("stephango.com", source_folder_for_note('source: "https://stephango.com/post"'))
self.assertEqual("Unknown Source", source_folder_for_note("title: Missing"))
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -B -m unittest tests.test_notes -v`

- [ ] **Step 3: Implement folder resolution and pass the resolved directory to note creation**

```python
folder = articles_path / source_folder_for_note(frontmatter)
folder.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run focused tests to verify success**

Run: `python -B -m unittest tests.test_notes tests.test_service tests.test_archive -v`

### Task 2: Existing-note migration and state recovery

**Files:**
- Modify: `article_importer/notes.py`, `article_importer/state.py`, `fetch_articles.py`
- Modify: `tests/test_notes.py`, `tests/test_service.py`, `tests/test_state.py`

**Interfaces:**
- Produces: `group_articles_by_source(articles_path: Path, state_path: Path) -> int`.

- [ ] **Step 1: Write failing tests**

```python
updated = group_articles_by_source(articles, state_path)
self.assertEqual(1, updated)
self.assertEqual(original_bytes, (articles / "Publisher" / note.name).read_bytes())
self.assertEqual(str(moved_path), stored_output_path)
```

- [ ] **Step 2: Run focused tests to verify failure**

Run: `python -B -m unittest tests.test_notes tests.test_state tests.test_service -v`

- [ ] **Step 3: Implement atomic moves, collision suffixes, and state output-path updates**

```python
target = _next_available_path(articles_path / source_folder, path.name)
path.replace(target)
state.update_output_path(str(path), str(target))
```

- [ ] **Step 4: Add `--group-by-source` migration command**

It loads configured paths, performs no feed import, prints `moved=<count>`, and rejects `--dry-run` combinations.

- [ ] **Step 5: Run full verification and commit**

Run: `python -B -m unittest discover -s tests -v; git diff --check`

Expected: all tests pass and no whitespace errors.
