# Architecture

OPMLark is a deterministic, local-first pipeline that turns RSS and Atom entries from OPML catalogs into durable Markdown. Routine ingestion does not call an AI service. AI tools may query the resulting Markdown or SQLite state later, but generated summaries are outside the ingestion system and never replace source articles.

## System boundaries

The workspace configuration and OPML catalogs are user-owned inputs. Python standard-library components parse them, fetch feeds, select eligible entries, invoke Defuddle, write Markdown, and record operational state in SQLite. Native operating-system schedulers only start the same ingestion command; Obsidian is an optional reader and sync layer.

```text
config.toml + OPML catalogs
            |
            v
    feed parsing and selection -----> SQLite state
            |
            v
       Defuddle CLI
            |
            v
   frontmatter + unchanged Markdown -----> any Markdown folder
```

Operational data remains under `data/` and outside the article collection. Imported Markdown is the durable user artifact.

## Configuration and feed catalogs

`config.toml` defines the article directory, importer policy, enabled OPML catalogs, source overrides, and portable schedules. Paths are resolved from the configuration file rather than the caller's working directory.

Each `[[feed_catalogs]]` entry points to an ordinary OPML file and may define a default storage folder. Feed outlines carry stable source IDs and may override their folder or be disabled. Configuration-level catalog and source disable lists take precedence. Source IDs must be unique across enabled catalogs. Storage paths are relative to the article directory and reject absolute paths and traversal.

OPML outline groups supply article topics. Adding or reorganizing feeds therefore changes data, not application code.

## Ingestion and state

The importer reads enabled catalogs, downloads each feed independently, and parses RSS or Atom entries into a common model. A failure in one feed or article is recorded without preventing other work.

SQLite is the authority for URL-level deduplication and retry state. It tracks feeds, entries, observation and publication times, attempt counts, errors, and output paths. Entries inside the configured rolling lookback are candidates; old entries are recorded without extraction. An entry without a usable publication time uses its first observation time. Successful entries become immutable imports. Failed entries retry only up to `max_attempts`, after which an explicit reset is required.

Dry runs calculate the same candidates without invoking Defuddle or changing the database or filesystem. A workspace-scoped, non-blocking lock makes overlapping scheduled runs exit successfully before ingestion begins.

## Markdown ownership

Defuddle is the extraction boundary. OPMLark prepends generated YAML frontmatter and preserves the returned Markdown body unchanged. New notes include article type, source URL, feed, topic, date provenance, and the importer marker used by safe migrations.

Notes are written beneath a configured source folder, then the feed name, source hostname, or `Unknown Source` fallback. Filenames are sanitized and collisions receive a numeric suffix; existing notes are never overwritten. After a successful import, OPMLark does not automatically rewrite or delete the article, so readers may annotate or reorganize it safely. Explicit migrations operate only on marked notes and preserve article bodies.

## Scheduling

Portable schedule intent lives in `[[schedules]]` blocks in `config.toml`. Named schedules support daily, weekly, monthly, and one-time local recurrences. Raw cron is deliberately excluded because it cannot always be translated faithfully across platforms.

The scheduler adapter projects enabled entries into:

- Windows Task Scheduler tasks;
- per-user macOS launchd agents;
- marked Linux user crontab entries.

Artifact identities combine a digest of the resolved workspace configuration path with the schedule ID. Reconciliation creates or updates desired entries, removes disabled or stale OPMLark entries, detects drift, and leaves unrelated native jobs untouched. Configuration remains authoritative after a backend failure so `schedule status` exposes the drift and `schedule apply` can retry it.

The CLI, TUI, JSON interface, and compatibility commands call the same configuration and reconciliation services. Scheduler output is appended to the workspace log. Missed-run behavior remains native to each operating system; the rolling lookback recovers eligible articles on the next successful run.

## Archive imports

Archive discovery is an explicit, resumable workflow separate from normal feed polling. Source-specific discovery adapters enumerate public historical URLs, then reuse the normal Defuddle, Markdown, and SQLite boundaries. Re-runs skip completed URLs, retry eligible failures, and recognize legacy notes by their source frontmatter.

## Design constraints

- Ingestion is token-free and works without an AI provider.
- Article bodies are source artifacts, not generated summaries.
- SQLite state never lives in the Markdown collection.
- Native scheduler changes are restricted to marked OPMLark artifacts.
- Configuration and plist writes use atomic replacement.
- Python 3.11+ and the standard library remain the portability baseline.

Durable trade-offs are recorded as short architecture decision records in [adr](adr/).
