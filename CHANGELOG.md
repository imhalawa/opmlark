# Changelog

All notable changes to OPMLark are documented here.

## 0.2.0 - 2026-08-02

- Add any number of named daily, weekly, monthly, or one-time schedules per workspace.
- Store portable schedule intent in `config.toml` and manage it through both the CLI and TUI.
- Reconcile schedules through Windows Task Scheduler, macOS launchd, or Linux cron without touching unrelated jobs.
- Add schedule status, enable, disable, edit, removal, repair, and stable JSON output.
- Keep 07:00 only as the backward-compatible default schedule time.
- Prevent overlapping ingestion runs with a workspace-scoped process lock.

## 0.1.0 - 2026-08-02

- Rebrand the personal importer as OPMLark.
- Add a portable generic Markdown workspace alongside legacy Obsidian configuration.
- Add a dependency-free TUI and JSON-capable automation CLI.
- Manage catalogs, categories, and feeds through canonical OPML files.
- List, search, and read collected articles through token-free machine commands.
- Bound automatic retries while keeping exhausted failures visible and resettable.
- Add Windows Task Scheduler and Unix cron integration.
- Add npm packaging for `npx` and `bunx`, with Defuddle installed as a dependency.
- Add community documentation, CI, and tag-driven GitHub/npm releases.
