# OPML Defuddle Articles

Imports articles newly published by the RSS and Atom feeds in the configured topic catalogs under `feeds/` into an Obsidian vault. Each imported note is processed by Defuddle and carries the marker `ingested_by: opml-defuddle-articles`.

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

Each `[[feed_catalogs]]` item selects one OPML file, gives it a stable `id`, and can set a default `folder` below `Sources/Articles`. Set `enabled = false` on a catalog or add its id to `feed_catalog.disabled_catalogs` to skip it. `feed_catalog.disabled_sources` skips a source id across all catalogs.

Each feed outline needs a stable `id` and `xmlUrl`. Set `enabled="false"` on an outline to skip only that source. A source-level `folder` overrides its catalog folder; otherwise the importer uses the catalog folder, then the feed/hostname fallback. Folders must be relative to `Sources/Articles` and cannot contain empty or traversal segments.

Example:

```toml
[[feed_catalogs]]
id = "company-engineering"
path = "feeds/company-engineering.opml"
folder = "Company Engineering"
enabled = true
```

```xml
<outline id="uber-engineering" text="Uber Engineering"
         xmlUrl="https://example.com/feed.xml"
         folder="Company Engineering/Uber" />
```

Verify every enabled endpoint before scheduling or after editing a catalog:

```powershell
& .\run-import.ps1 --validate-catalogs
```

Booking.com has a technical blog, but no public RSS/Atom endpoint was discoverable; Adyen and Mollie likewise have no verified technical feed endpoint. Uber Engineering publishes an RSS link but its endpoint currently rejects the importer's request. They are intentionally documented rather than enabled. The enabled Netherlands-focused sources are bol Techlab and Weaviate, whose public feeds validate successfully.

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
