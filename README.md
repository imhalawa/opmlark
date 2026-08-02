# OPMLark

> Give it OPML. Get clean Markdown.

OPMLark monitors the RSS and Atom feeds in your OPML catalogs, extracts newly published articles with [Defuddle](https://github.com/kepano/defuddle), and preserves them as readable Markdown.

Collection is automatic and token-free. The resulting files work with Obsidian, ordinary folders, Git, full-text search, scripts, and optional AI tools.

## Why OPMLark

- **Open inputs:** subscriptions and categories remain normal OPML.
- **Open outputs:** every article is a normal Markdown file with YAML frontmatter.
- **Local-first:** SQLite tracks ingestion state beside the workspace.
- **Write-once:** OPMLark never rewrites a successfully imported article, so annotations are safe.
- **AI-optional:** scheduled collection consumes no AI tokens. AI can query selected files later.
- **Human and machine friendly:** use the TUI, non-interactive commands, or stable `--json` output.

## Prerequisites

- Node.js 18 or newer, for `npx`/`bunx` and the bundled Defuddle dependency.
- Python 3.11 or newer. OPMLark's core uses only the Python standard library.
- Network access to the feeds and articles you subscribe to.

## Quick start

Create a workspace without installing anything globally:

```sh
mkdir my-reading
cd my-reading
npx -y opmlark init
npx -y opmlark
```

Running `opmlark` without a command opens the terminal interface. Bun users can replace `npx -y` with `bunx`.

Add a feed non-interactively:

```sh
npx -y opmlark category add \
  --catalog reading \
  --name "Engineering/System Design"

npx -y opmlark feed add \
  --catalog reading \
  --category "Engineering/System Design" \
  --id example-engineering \
  --name "Example Engineering" \
  --url "https://example.com/feed.xml"

npx -y opmlark run --dry-run
npx -y opmlark run
```

For regular use, install the command globally:

```sh
npm install --global opmlark
opmlark doctor
opmlark schedule install --time 07:00
```

The schedule command creates or updates a Windows Scheduled Task on Windows and an idempotent crontab entry on macOS and Linux. A global installation is recommended because scheduled jobs need a stable executable path.

## Workspace

`opmlark init` creates only portable files:

```text
my-reading/
├── config.toml
├── feeds/
│   └── reading.opml
├── articles/
└── data/                    # generated runtime state
    ├── articles.sqlite3
    └── importer.log
```

The runtime paths are `data/articles.sqlite3` and `data/importer.log`; neither belongs in version control.

`config.toml` selects the Markdown output directory, lookback window, Defuddle executable, and one or more `feed_catalogs`:

```toml
[importer]
output_path = "articles"
defuddle_executable = "defuddle"
lookback_days = 90
max_attempts = 3

[[feed_catalogs]]
id = "reading"
path = "feeds/reading.opml"
folder = "Reading"
```

Each feed `outline` needs a stable `id` and `xmlUrl`. Nested outlines become categories:

```xml
<outline text="Engineering">
  <outline text="System Design">
    <outline id="example-engineering"
             text="Example Engineering"
             xmlUrl="https://example.com/feed.xml" />
  </outline>
</outline>
```

OPML is the canonical editable catalog. The TUI and commands modify it directly rather than hiding subscriptions in a private database.

## Obsidian

Obsidian is a preset, not a requirement. Point `output_path` at any directory inside a vault:

```toml
[importer]
output_path = "C:/Users/you/Documents/My Vault/Sources/Articles"
defuddle_executable = "defuddle"
lookback_days = 90
```

The files can then sync, open, and receive annotations like any other Markdown notes.

## Automation and AI

All list, status, and mutation commands support JSON output:

```sh
opmlark status --json
opmlark catalog list --json
opmlark category list --json
opmlark feed list --json
opmlark run --dry-run --json
opmlark article list --since 2026-08-01 --json
opmlark article search "distributed systems" --json
opmlark article read --url "https://example.com/article" --json
```

An AI workflow should first query this structured metadata, then read only the selected Markdown files. OPMLark does not generate or store summaries.

## Ingestion behavior

Every run considers visible entries inside `lookback_days`. SQLite prevents repeat imports. Entries older than the cutoff are recorded as seeded. Failed entries retry up to `max_attempts`, then remain visible for inspection instead of breaking every scheduled run forever.

Undated entries use their first observation time and receive `publication_date_source: "observed"`. Feed timestamps use `publication_date_source: "feed"`.

The generated frontmatter includes `type`, title, article URL, feed, category, dates, author when available, tags, and `ingested_by: opmlark`. The Defuddle Markdown body is written unchanged.

## Commands

```text
opmlark                         Open the TUI
opmlark init                    Create a workspace
opmlark run [--dry-run]         Ingest or preview new articles
opmlark status                  Show collection state
opmlark doctor                  Check prerequisites
opmlark catalog list|add|disable Manage OPML catalogs
opmlark category list|add       Manage nested categories
opmlark feed list|add|remove    Manage subscriptions
opmlark failure list|retry      Inspect or explicitly retry failed articles
opmlark article list|search|read Query the collection without AI tokens
opmlark schedule show|install|remove
```

## Existing checkout compatibility

The original project layout remains supported. Existing `vault_path`, `feeds/`, `run-import.ps1`, `install-scheduled-task.ps1`, `--validate-catalogs`, and migration commands continue to work. Existing notes marked `ingested_by: opml-defuddle-articles` remain recognized; new notes use `ingested_by: opmlark`.

The legacy scheduled task can still be removed with `Unregister-ScheduledTask`; new installations should use `opmlark schedule remove`.

## Development

```sh
python -m unittest discover -v
npm install
npm run smoke
npm pack --dry-run
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and [CONTEXT.md](CONTEXT.md) for the project language.

## License

MIT
