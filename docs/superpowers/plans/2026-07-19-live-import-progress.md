# Live Import Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show immediate, readable progress in the importer’s PowerShell host during normal and scheduled runs.

**Architecture:** `ImportService` owns progress events because it knows the feed and article lifecycle. The CLI supplies a flushed `print` callback, preserving the service’s dependency injection and leaving logging, Defuddle content, note creation, and state handling unchanged.

**Tech Stack:** Python 3.12, standard-library `unittest`, Windows Task Scheduler, PowerShell.

## Global Constraints

- Preserve Defuddle markdown exactly; only existing frontmatter generation may write note metadata.
- Preserve the 90-day rolling lookback and SQLite state behavior.
- Do not change OPML catalogs or the user’s uncommitted `feeds/psychology.opml` edit.
- Console writes must flush immediately so the scheduled PowerShell window is never blank while work is in progress.

---

### Task 1: Progress event interface and service events

**Files:**
- Modify: `article_importer/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: optional `progress: Callable[[str], None]` passed to `ImportService`.
- Produces: start, numbered feed, article-begin, success, and failure progress events.

- [ ] **Step 1:** Add a failing `ImportServiceTests.test_emits_progress_for_feed_and_imported_article` using an `events.append` callback.
- [ ] **Step 2:** Run `python -B -m unittest tests.test_service.ImportServiceTests.test_emits_progress_for_feed_and_imported_article -v`; expect constructor failure because `progress` is unsupported.
- [ ] **Step 3:** Add the optional reporter, emitting `Starting import: N feeds, N-day lookback`, `[N/N] Fetching Source`, `Defuddling: URL`, and `Imported: title` around existing operations.
- [ ] **Step 4:** Re-run the focused test; expect PASS.

### Task 2: Flushed console reporter

**Files:**
- Modify: `fetch_articles.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `ImportService(..., progress=_print_progress)`.
- Produces: immediate standard-output messages through `print(message, flush=True)`.

- [ ] **Step 1:** Add a failing CLI test that asserts `ImportService` receives the module-level `_print_progress` callback.
- [ ] **Step 2:** Run `python -B -m unittest tests.test_service.FetchArticlesCliTests.test_cli_passes_a_flushed_console_progress_reporter -v`; expect failure because no callback is passed.
- [ ] **Step 3:** Implement `_print_progress` and pass it to `ImportService`.
- [ ] **Step 4:** Re-run the focused test; expect PASS.
- [ ] **Step 5:** Run `python -B -m unittest discover -s tests -q` and commit only the implementation/test/docs files, leaving the user’s OPML edit untouched.
