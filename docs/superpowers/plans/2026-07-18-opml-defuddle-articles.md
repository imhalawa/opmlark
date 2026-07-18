
# OPML-driven Defuddled Article Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable daily importer that turns newly published OPML feed entries into Defuddle-generated Obsidian articles.

**Architecture:** Standard-library Python parses OPML and RSS/Atom, maintains per-feed URL state in project-local SQLite, and calls the installed Defuddle CLI for every unseen article. A PowerShell wrapper finds the project relative to itself; a second script registers the daily Windows task.

**Tech Stack:** Python 3.11+ standard library, Defuddle CLI 0.19+, PowerShell 5.1+, Windows Task Scheduler.

## Global Constraints

- Project root is `R:\opml-defuddle-articles`; never depend on the caller's working directory.
- Store every note in `<vault_path>/Sources/Articles`, supplied by `config.toml`.
- Use only Python standard-library modules; require an installed `defuddle` CLI.
- `feeds.opml` is the editable source of truth. Its parent outline becomes the note topic.
- First successful sighting of a feed seeds its visible URLs in SQLite; it must create no notes.
- Write Defuddle's returned Markdown byte-for-byte unchanged after generated YAML frontmatter.
- Every imported note must contain `ingested_by: opml-defuddle-articles`.
- Keep SQLite, logs, and operational state outside the vault. Never overwrite an existing article.
- Failed article imports must retry on subsequent runs.
- The schedule must run at local 07:00 every day with Obsidian closed.

---

## File Structure

```text
R:\opml-defuddle-articles\
  .gitignore
  README.md
  config.toml
  feeds.opml
  fetch_articles.py
  run-import.ps1
  install-scheduled-task.ps1
  article_importer/
    __init__.py
    models.py
    configuration.py
    parsing.py
    state.py
    defuddle.py
    notes.py
    service.py
  tests/
    __init__.py
    fixtures.py
    test_parsing.py
    test_state.py
    test_notes.py
    test_service.py
```

### Task 1: Bootstrap configuration and feed parsing

**Files:**

- Create: `.gitignore`, `config.toml`, `feeds.opml`
- Create: `article_importer/__init__.py`, `article_importer/models.py`, `article_importer/configuration.py`, `article_importer/parsing.py`
- Create: `tests/__init__.py`, `tests/fixtures.py`, `tests/test_parsing.py`

**Interfaces:**

- Produces `load_config(path: Path) -> ImporterConfig`.
- Produces `parse_opml(path: Path) -> list[FeedSubscription]`.
- Produces `parse_feed(xml: bytes, subscription: FeedSubscription) -> list[FeedEntry]`.

- [ ] **Step 1: Write failing standard-library tests**

```python
class ParsingTests(unittest.TestCase):
    def test_opml_uses_parent_outline_as_topic(self) -> None:
        path = self.temp / "feeds.opml"
        path.write_text(OPML, encoding="utf-8")
        self.assertEqual(
            [FeedSubscription("System Design", "ByteByteGo",
             "https://example.test/feed", "https://example.test")],
            parse_opml(path),
        )

    def test_rss_and_atom_links_are_read(self) -> None:
        feed = FeedSubscription("Algorithms", "Example", "https://example.test/feed")
        self.assertEqual("https://example.test/rss", parse_feed(RSS, feed)[0].url)
        self.assertEqual("https://example.test/atom", parse_feed(ATOM, feed)[0].url)

    def test_config_requires_articles_directory(self) -> None:
        config = self.temp / "config.toml"
        config.write_text('[importer]\nvault_path = "C:/missing"\n', encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "Sources/Articles"):
            load_config(config)
```

- [ ] **Step 2: Verify the test fails**

Run: `python -m unittest tests.test_parsing -v`

Expected: `ModuleNotFoundError: No module named 'article_importer'`.

- [ ] **Step 3: Implement the parsing interfaces**

```python
@dataclass(frozen=True)
class FeedSubscription:
    topic: str
    name: str
    feed_url: str
    home_url: str | None = None

@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published: datetime | None
    subscription: FeedSubscription
```

Use `tomllib.load` for `ImporterConfig(vault_path, articles_path, defuddle_executable)`; resolve relative executable paths from the config parent and raise `ConfigurationError` if the vault or articles directory is missing. Use `xml.etree.ElementTree` for OPML; accept only child outlines with `xmlUrl`, use their immediate parent `text` for topic, and select `title` then `text` for publisher name. In `parse_feed`, support RSS `channel/item` and Atom `entry`; prefer Atom `rel="alternate"` links, resolve relative links with `urljoin`, parse RSS `pubDate` / Atom `published` or `updated`, and discard duplicate or missing URLs.

- [ ] **Step 4: Add the editable starter files**

```toml
# config.toml
[importer]
vault_path = "C:/Users/imhal/Documents/Traces"
defuddle_executable = "defuddle"
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><head><title>Article feeds</title></head><body>
  <outline text="System Design">
    <outline text="ByteByteGo" title="ByteByteGo" type="rss" xmlUrl="https://blog.bytebytego.com/feed"/>
    <outline text="The Morning Paper" title="The Morning Paper" type="rss" xmlUrl="https://blog.acolyer.org/feed/"/>
    <outline text="Architecture Notes" title="Architecture Notes" type="rss" xmlUrl="https://architecturenotes.co/feed/"/>
  </outline>
  <outline text="Algorithms and Data Structures">
    <outline text="Eli Bendersky" title="Eli Bendersky" type="rss" xmlUrl="https://eli.thegreenplace.net/feeds/all.atom.xml"/>
    <outline text="Jeremy Kun" title="Jeremy Kun" type="rss" xmlUrl="https://www.jeremykun.com/feed/"/>
    <outline text="Daniel Lemire" title="Daniel Lemire" type="rss" xmlUrl="https://lemire.me/blog/feed/"/>
  </outline>
  <outline text="Psychology / ADHD">
    <outline text="CHADD" title="CHADD" type="rss" xmlUrl="https://chadd.org/feed/"/>
    <outline text="ADDA" title="ADDA" type="rss" xmlUrl="https://add.org/feed/"/>
    <outline text="ADHD Europe" title="ADHD Europe" type="rss" xmlUrl="https://www.adhdeurope.eu/feed/"/>
    <outline text="ADDitude" title="ADDitude" type="rss" xmlUrl="https://www.additudemag.com/feed/"/>
  </outline>
</body></opml>
```

```gitignore
data/
__pycache__/
*.py[cod]
.venv/
```

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.test_parsing -v`

Expected: all parser and configuration tests pass.

```powershell
git add .gitignore config.toml feeds.opml article_importer tests
git commit -m "feat: add OPML feed parsing"
```

### Task 2: Add SQLite first-seen, deduplication, and retry state

**Files:**

- Create: `article_importer/state.py`
- Create: `tests/test_state.py`

**Interfaces:**

- Produces `StateStore(path: Path)`.
- Produces `candidates(subscription, entries, dry_run=False) -> FeedBatch`, where `FeedBatch` has `first_seen: bool`, `seeded: int`, and `candidates: tuple[FeedEntry, ...]`.
- Produces `mark_imported(feed_url, article_url, output_path)` and `mark_failed(feed_url, article_url, error)`.

- [ ] **Step 1: Write failing state tests**

```python
def test_first_observation_seeds_and_returns_no_candidates(self) -> None:
    with StateStore(self.database) as state:
        batch = state.candidates(SUBSCRIPTION, [ENTRY])
    self.assertTrue(batch.first_seen)
    self.assertEqual(1, batch.seeded)
    self.assertEqual((), batch.candidates)

def test_failed_and_new_are_candidates_but_imported_is_not(self) -> None:
    with StateStore(self.database) as state:
        state.candidates(SUBSCRIPTION, [ENTRY])
        state.mark_imported(SUBSCRIPTION.feed_url, ENTRY.url, "Article - entry.md")
        state.mark_failed(SUBSCRIPTION.feed_url, FAILED.url, "timeout")
        batch = state.candidates(SUBSCRIPTION, [ENTRY, FAILED, NEW])
    self.assertEqual({FAILED.url, NEW.url}, {item.url for item in batch.candidates})
```

- [ ] **Step 2: Verify the test fails**

Run: `python -m unittest tests.test_state -v`

Expected: `ModuleNotFoundError: No module named 'article_importer.state'`.

- [ ] **Step 3: Implement transactional SQLite state**

Create `feeds(feed_url PRIMARY KEY, name, topic, initialized_at)` and `entries(feed_url, article_url, title, published, status CHECK(status IN ('seeded','imported','failed')), output_path, error_message, seen_at, updated_at, PRIMARY KEY(feed_url, article_url))`. In one transaction, a previously unseen feed inserts itself and all visible entry URLs as `seeded`, then returns no candidates. An initialized feed returns every currently visible untracked URL plus any visible `failed` URL; it never returns `seeded` or `imported`. `dry_run=True` computes the same result then rolls back. All timestamps are UTC ISO-8601 strings.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_state -v`

Expected: first-seen, duplicate, dry-run, and retry tests pass.

```powershell
git add article_importer/state.py tests/test_state.py
git commit -m "feat: track feed state in sqlite"
```

### Task 3: Use Defuddle and write marked Obsidian notes

**Files:**

- Create: `article_importer/defuddle.py`, `article_importer/notes.py`
- Create: `tests/test_notes.py`

**Interfaces:**

- Produces `run_defuddle(url: str, executable: str) -> DefuddledArticle`.
- Produces `build_frontmatter(article, entry, imported_at) -> str`.
- Produces `create_note(articles_path, frontmatter, markdown) -> Path`.

- [ ] **Step 1: Write failing tests**

```python
@patch("article_importer.defuddle.subprocess.run")
def test_defuddle_returns_markdown_without_mutation(self, run: Mock) -> None:
    run.return_value = CompletedProcess([], 0, json.dumps(
        {"title": "A title", "content": "## Original\n\nunchanged\n"}), "")
    article = run_defuddle("https://example.test/article", "defuddle")
    self.assertEqual("## Original\n\nunchanged\n", article.markdown)
    self.assertEqual(
        ["defuddle", "parse", "https://example.test/article", "--json", "--md"],
        run.call_args.args[0],
    )

def test_note_has_marker_and_unchanged_body(self) -> None:
    body = "## Original\n\nunchanged\n"
    output = create_note(self.articles, build_frontmatter(ARTICLE, ENTRY, NOW), body)
    saved = output.read_text(encoding="utf-8")
    self.assertIn("ingested_by: opml-defuddle-articles\n", saved)
    self.assertTrue(saved.endswith(body))
```

- [ ] **Step 2: Verify the test fails**

Run: `python -m unittest tests.test_notes -v`

Expected: imports fail because Defuddle and note modules do not exist.

- [ ] **Step 3: Implement the boundary and writer**

Call exactly `subprocess.run([executable, "parse", url, "--json", "--md"], capture_output=True, text=True, check=False, timeout=120)`. Raise `DefuddleError` for missing executable, non-zero exit, invalid JSON, or absent/whitespace-only `content`; otherwise preserve `payload["content"]` exactly. Generate frontmatter by JSON-quoting scalar YAML values, and always include:

```yaml
---
title: "..."
source: "https://..."
feed: "Publisher"
topic: "System Design"
published: "..."
imported: "..."
ingested_by: opml-defuddle-articles
tags:
  - source/articles
  - topic/system-design
---
```

Include `author` only when supplied by Defuddle. Use `Article - <safe title>.md`, replace Windows-reserved/control characters, cap the title portion at 140 characters, fall back to `Untitled article`, and use exclusive file creation. Append ` (2)`, ` (3)`, etc. on collisions. Write exactly `frontmatter + markdown`; do not strip, transform, or append to the body.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_notes -v`

Expected: command, marker, unchanged-body, and collision tests pass.

```powershell
git add article_importer/defuddle.py article_importer/notes.py tests/test_notes.py
git commit -m "feat: save marked defuddled articles"
```

### Task 4: Orchestrate feeds, dry runs, logging, and errors

**Files:**

- Create: `article_importer/service.py`, `fetch_articles.py`, `tests/test_service.py`
- Modify: `tests/fixtures.py`

**Interfaces:**

- Produces `ImportService.run(dry_run: bool) -> RunSummary`.
- Produces command `python fetch_articles.py [--config PATH] [--dry-run]`.
- `RunSummary` contains `seeded`, `imported`, `failed_entries`, and `failed_feeds`.

- [ ] **Step 1: Write failing service tests**

```python
def test_first_run_seeds_without_defuddle(self) -> None:
    summary = self.service.run(dry_run=False)
    self.assertEqual(2, summary.seeded)
    self.assertEqual(0, summary.imported)
    self.defuddle.assert_not_called()

def test_later_new_entry_is_imported_and_marked(self) -> None:
    self.service.run(dry_run=False)
    self.fetcher.return_value = RSS_WITH_NEW_ENTRY
    summary = self.service.run(dry_run=False)
    self.assertEqual(1, summary.imported)
    note = next(self.articles.glob("Article - *.md"))
    self.assertIn("ingested_by: opml-defuddle-articles", note.read_text(encoding="utf-8"))

def test_bad_feed_does_not_prevent_other_feed(self) -> None:
    summary = self.service.run(dry_run=False)
    self.assertEqual(1, summary.failed_feeds)
    self.assertGreaterEqual(summary.seeded, 1)
```

- [ ] **Step 2: Verify the test fails**

Run: `python -m unittest tests.test_service -v`

Expected: `ModuleNotFoundError: No module named 'article_importer.service'`.

- [ ] **Step 3: Implement orchestration**

Inject `fetch_bytes(url) -> bytes` and the Defuddle callable into `ImportService` for tests. Production fetching uses `urllib.request.Request` with `User-Agent: opml-defuddle-articles/1.0` and a 30-second timeout. Catch each feed's network/XML failure, log it, increment `failed_feeds`, and continue. Catch each Defuddle or note creation failure, call `mark_failed`, log URL and error, increment `failed_entries`, and continue. Dry run must not call Defuddle or write notes/database. `fetch_articles.py` must resolve its project root from `__file__`, write UTF-8 records to `data/importer.log`, print a summary, and exit 1 for any failure or invalid config.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest discover -s tests -v`

Expected: all unit tests pass.

```powershell
git add article_importer/service.py fetch_articles.py tests
git commit -m "feat: orchestrate article imports"
```

### Task 5: Add the daily runner, scheduler, documentation, and live seeding

**Files:**

- Create: `run-import.ps1`, `install-scheduled-task.ps1`, `README.md`
- Generate: `data/articles.sqlite3`, `data/importer.log` (ignored by Git)

**Interfaces:**

- Produces a runner that forwards arguments and exit code.
- Produces an idempotent task named `OPML Defuddle Articles`.

- [ ] **Step 1: Write the runner and scheduler**

```powershell
# run-import.ps1
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$projectRoot = Split-Path -Parent $PSCommandPath
& python (Join-Path $projectRoot 'fetch_articles.py') @Arguments
exit $LASTEXITCODE
```

```powershell
# install-scheduled-task.ps1
[CmdletBinding()]
param()
$projectRoot = Split-Path -Parent $PSCommandPath
$runner = Join-Path $projectRoot 'run-import.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $runner)
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'OPML Defuddle Articles' -Action $action -Trigger $trigger -Settings $settings -Description 'Imports new OPML feed articles through Defuddle.' -Force | Out-Null
```

Document prerequisite checks, configuration, copying an `outline` into `feeds.opml`, no-backfill first run, manual and dry-run commands, updating/removing the task, database/log locations, and cleanup search `ingested_by: opml-defuddle-articles`.

- [ ] **Step 2: Run all tests and install the schedule**

Run:

```powershell
python -m unittest discover -s tests -v
& 'R:\opml-defuddle-articles\run-import.ps1' --dry-run
& 'R:\opml-defuddle-articles\install-scheduled-task.ps1'
Get-ScheduledTask -TaskName 'OPML Defuddle Articles' | Format-List TaskName,State,Actions,Triggers
```

Expected: tests pass; dry run reports prospective first-run seeding; the scheduled task action uses the project-local runner and trigger is 07:00.

- [ ] **Step 3: Seed the live baseline with no articles created**

Before the live run, count current marker notes:

```powershell
(Get-ChildItem 'C:\Users\imhal\Documents\Traces\Sources\Articles' -Filter '*.md' |
  Select-String -SimpleMatch 'ingested_by: opml-defuddle-articles' | Measure-Object).Count
```

Run: `& 'R:\opml-defuddle-articles\run-import.ps1'`

Expected: it reports `imported=0`, records all current visible entries as `seeded`, and does not add marker notes.

- [ ] **Step 4: Verify and commit source files**

Run:

```powershell
& 'R:\opml-defuddle-articles\run-import.ps1' --dry-run
git status --short
```

Expected: no imports unless a publisher posted after seeding; `data/` is absent from Git status.

```powershell
git add run-import.ps1 install-scheduled-task.ps1 README.md
git commit -m "feat: add daily scheduled runner"
```

## Plan Self-Review

- Spec coverage: Tasks 1–2 cover editable OPML, portable configuration, RSS/Atom, no-backfill seeding, and SQLite. Task 3 preserves Defuddle body text and adds the required marker. Task 4 covers retries, errors, logs, dry run, and exit status. Task 5 provides the daily 07:00 schedule, operating instructions, and live no-backfill verification.
- Placeholder scan: no open placeholders or undefined implementation tasks remain.
- Type consistency: `FeedSubscription` and `FeedEntry` are created in Task 1; Task 2 returns `FeedBatch`; Task 3 returns `DefuddledArticle` and a note path; Task 4 composes those types.

