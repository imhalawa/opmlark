# OPML-driven Defuddled Article Importer

## Purpose

Create a portable Windows project that watches topic-organized RSS and Atom feeds, imports only articles published after initial subscription, extracts each article through Defuddle, and saves the resulting Markdown to an Obsidian vault.

The project is installed at `R:\opml-defuddle-articles`. It can be launched from any working directory. The only environment-specific setting is the vault path in `config.toml`.

## Requirements

- Article destination: `<vault_path>/Sources/Articles`.
- Every article body is Defuddle-generated Markdown and is otherwise untouched.
- The importer may prepend and maintain YAML frontmatter only. Every imported article contains `ingested_by: opml-defuddle-articles` for safe cleanup.
- Feed definitions are kept in one editable OPML file. Adding a feed requires no code change.
- No backfill: a newly observed feed has its current entries recorded as seen but none are downloaded.
- Processed URLs and run results live outside the vault in a SQLite database.
- The importer runs daily at 07:00 using Windows Task Scheduler, without requiring Obsidian to be open.

## Project layout

```text
R:\opml-defuddle-articles\
  config.toml
  feeds.opml
  fetch_articles.py
  run-import.ps1
  install-scheduled-task.ps1
  requirements.txt
  data\
    articles.sqlite3             # generated, excluded from source control
    importer.log                 # generated, excluded from source control
  tests\
  docs\superpowers\specs\
```

`config.toml` stores `vault_path` and optional executable settings. Paths are resolved relative to the project directory where appropriate, never the caller's current directory.

## Feed configuration

`feeds.opml` uses topic outline groups and standard `xmlUrl` feed entries. The topic group becomes the `topic` frontmatter property and tag. Feed entry attributes also carry the publisher name and optional home page.

The initial OPML includes these reachable feeds:

| Topic | Publisher | Feed |
| --- | --- | --- |
| System Design | ByteByteGo | `https://blog.bytebytego.com/feed` |
| System Design | The Morning Paper | `https://blog.acolyer.org/feed/` |
| System Design | Architecture Notes | `https://architecturenotes.co/feed/` |
| Algorithms and Data Structures | Eli Bendersky | `https://eli.thegreenplace.net/feeds/all.atom.xml` |
| Algorithms and Data Structures | Jeremy Kun | `https://www.jeremykun.com/feed/` |
| Algorithms and Data Structures | Daniel Lemire | `https://lemire.me/blog/feed/` |
| Psychology / ADHD | CHADD | `https://chadd.org/feed/` |
| Psychology / ADHD | ADDA | `https://add.org/feed/` |
| Psychology / ADHD | ADHD Europe | `https://www.adhdeurope.eu/feed/` |
| Psychology / ADHD | ADDitude | `https://www.additudemag.com/feed/` |

## Import flow

1. Launch from `run-import.ps1`, which finds the project directory from its own location and launches Python with the absolute script path.
2. Read `config.toml`, validate that the configured vault and `Sources/Articles` directory exist, then parse `feeds.opml` with the standard-library XML parser.
3. Download each RSS or Atom feed with a descriptive User-Agent. Extract the canonical entry link, title, publication date, and feed identity.
4. For an unknown feed, insert its currently visible entry URLs as `seeded` into SQLite and do not create notes. This establishes the no-backfill baseline.
5. For known feeds, identify entries not already stored in SQLite. Each is a candidate for import.
6. For each candidate, invoke `defuddle parse <article-url> --json`; use its returned Markdown content verbatim as the note body.
7. Construct YAML frontmatter from Defuddle and feed metadata, including `title`, `source`, `feed`, `topic`, `published`, `imported`, tags, and the mandatory `ingested_by: opml-defuddle-articles` marker. Write it followed by the unchanged Defuddle Markdown to the Articles folder with the existing `Article - <title>.md` convention.
8. Store the successful URL, canonical URL, output filename, and timestamp in SQLite. Failed downloads and parsing attempts are recorded but remain eligible for retry on the next run.
9. Append concise run results to `data/importer.log` and return a non-zero exit code for operational failures.

The deduplication key is the combination of feed URL and canonical article URL. A filename collision is resolved deterministically without overwriting an existing file.

## SQLite state

SQLite is standard-library backed (`sqlite3`) and never placed in the vault. It tracks feeds, entries, statuses (`seeded`, `imported`, `failed`), output paths, errors, and timestamps. This makes state portable with the project while keeping Obsidian notes clean and independently deletable by their marker.

## Error handling

- An unavailable feed is logged and does not stop other feeds.
- Invalid XML, entries without usable links, invalid Defuddle JSON, and empty Defuddle output are logged and skipped.
- Existing notes are never overwritten.
- Failed entries are retried until a successful import is committed to SQLite.
- ADHD-related material is archived without commentary, interpretation, or medical advice.

## Scheduler

`install-scheduled-task.ps1` registers or updates a task named `OPML Defuddle Articles` to run `run-import.ps1` daily at 07:00 local time. The task runs with the current user's least-privileged account and does not depend on an interactive Obsidian session.

## Verification

Automated tests cover OPML topic parsing, RSS and Atom entry parsing, first-seen feed seeding, new-entry detection, frontmatter construction and marker presence, filename collision handling, and failure retry semantics. A dry-run mode will show which entries would be seeded or imported without writing notes or changing the database. The scheduled task setup is verified by inspecting its configured action and trigger.
