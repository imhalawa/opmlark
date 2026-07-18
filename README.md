# OPML Defuddle Articles

Imports articles newly published by the RSS and Atom feeds in `feeds.opml` into an Obsidian vault. Each imported note is processed by Defuddle and carries the marker `ingested_by: opml-defuddle-articles`.

## Prerequisites

- Windows PowerShell with access to Task Scheduler.
- Python 3 available as `python` on `PATH`.
- The `defuddle` executable available on `PATH` (or an explicit executable path in `config.toml`).
- Network access to the configured feeds and article pages.
- An Obsidian vault containing `Sources/Articles`.

Check the required executables before installing the schedule:

```powershell
python --version
defuddle --version
Test-Path 'C:\Users\imhal\Documents\Traces\Sources\Articles'
```

## Configuration and feeds

Edit `config.toml` to set `vault_path`, `lookback_days`, and, when necessary, `defuddle_executable`. Bare executable names (such as `defuddle`) resolve through `PATH`; explicit relative paths resolve from the configuration file's directory.

Put your feed subscriptions in `feeds.opml`. Export or copy an OPML `outline` into its `<body>`; each feed outline needs an `xmlUrl`. A nested parent outline is used as the article topic, and its children become feed subscriptions.

## Rolling three-month lookback

Every run considers visible entries from the trailing `lookback_days` window (set to 90 days in the supplied configuration), including when you add a new feed. Eligible URLs are Defuddled once; SQLite prevents repeat imports on later daily runs. Older visible entries are recorded as `seeded` and ignored.

When a feed omits an article date, the importer uses its observation time so the article is eligible once. Its note records `publication_date_source: "observed"`; feed-provided timestamps use `publication_date_source: "feed"`.

Preview a run without changing the SQLite state, creating notes, or updating operational logs. The summary reports entries that would be imported or retried:

```powershell
& .\run-import.ps1 --dry-run
```

Run the importer manually:

```powershell
& .\run-import.ps1
```

## Frontmatter migrations

To add `type: article` to importer-created notes that predate the property:

```powershell
& .\run-import.ps1 --add-article-type
```

To add a missing topic only to legacy notes whose top-level frontmatter is exactly `type: article` (never importer-marked notes and never notes that already have a topic):

```powershell
& .\run-import.ps1 --add-topics
```

The topic migration uses title and tag keywords in this precedence: `Psychology (ADHD)`, `Algorithms and Data Structures`, `System Design`, `Finance`, `Science`, `Personal Development`, then `Software Engineering` as the fallback. Both migrations update YAML frontmatter only, preserve the article body, and are idempotent.

## Daily schedule

Install or update the idempotent daily task. It is named `OPML Defuddle Articles`, runs the project-local `run-import.ps1`, and is scheduled for local 07:00 with a 30-minute execution limit:

```powershell
& .\install-scheduled-task.ps1
Get-ScheduledTask -TaskName 'OPML Defuddle Articles' | Format-List TaskName,State,Actions,Triggers
```

Re-run the installer after moving the project or changing its desired task configuration. To remove the task:

```powershell
Unregister-ScheduledTask -TaskName 'OPML Defuddle Articles' -Confirm:$false
```

## State, logs, and cleanup

The importer keeps its state in `data/articles.sqlite3` and appends operational messages to `data/importer.log`. Both are local runtime data and ignored by Git.

To locate imported notes in Obsidian, search:

```text
ingested_by: opml-defuddle-articles
```
