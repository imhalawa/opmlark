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

Edit `config.toml` to set `vault_path` and, when necessary, `defuddle_executable`. Bare executable names (such as `defuddle`) resolve through `PATH`; explicit relative paths resolve from the configuration file's directory.

Put your feed subscriptions in `feeds.opml`. Export or copy an OPML `outline` into its `<body>`; each feed outline needs an `xmlUrl`. A nested parent outline is used as the article topic, and its children become feed subscriptions.

## First run and no-backfill behavior

The first live run is a **no-backfill** baseline: every entry currently visible in each feed is recorded as `seeded`, with `imported=0`. It does not create article notes. Only entries that appear after that baseline are imported on later runs.

Preview a run without changing the SQLite state, creating notes, or updating operational logs. The summary reports entries that would be imported or retried:

```powershell
& .\run-import.ps1 --dry-run
```

Run the importer manually:

```powershell
& .\run-import.ps1
```

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
