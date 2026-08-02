# Portable Multiple Schedules Design

## Goal

OPMLark workspaces may define any number of named ingestion schedules. OPMLark stores portable scheduling intent in `config.toml` and reconciles it into the current user's native scheduler on Windows, macOS, or Linux. The existing 07:00 behavior remains a convenience default, not a global product assumption.

## Source of truth

Configuration is authoritative. The CLI and TUI edit the same `[[schedules]]` entries; they do not maintain a separate schedule database. Native tasks are projections that `opmlark schedule apply` can recreate after moving a workspace or reinstalling OPMLark.

```toml
[[schedules]]
id = "morning"
frequency = "daily"
at = "07:00"
enabled = true

[[schedules]]
id = "weekend"
frequency = "weekly"
days = ["sat", "sun"]
at = "09:30"

[[schedules]]
id = "monthly-review"
frequency = "monthly"
day = 1
at = "18:00"

[[schedules]]
id = "special-import"
frequency = "once"
date = "2026-09-15"
at = "12:00"
```

Schedule IDs are stable, workspace-unique identifiers suitable for commands and native task names. Schedules are enabled unless `enabled = false` is specified. Times use strict 24-hour `HH:MM` notation and the host's local timezone.

## Portable recurrence model

The first portable model supports:

- `daily`: every day at `at`.
- `weekly`: one or more unique weekday names in `days`, at `at`.
- `monthly`: a calendar day from 1 through 31 in `day`, at `at`; months without that day skip the occurrence.
- `once`: one ISO `YYYY-MM-DD` local date in `date`, at `at`.

OPMLark will not accept raw cron expressions in this model. Cron syntax has semantics that cannot always be represented faithfully by Windows Task Scheduler or macOS launchd. A future version may add more portable recurrence types without changing existing entries.

## Management surfaces

The non-interactive interface is:

```text
opmlark schedule list
opmlark schedule add [recurrence options]
opmlark schedule edit ID [recurrence options]
opmlark schedule enable ID
opmlark schedule disable ID
opmlark schedule remove ID
opmlark schedule apply
opmlark schedule status
```

`schedule add` and `schedule edit` use explicit portable flags when supplied. When required recurrence details are omitted in an interactive terminal, they run a guided prompt. The TUI exposes the same operations through the same application functions. Commands support `--json` for scripts and AI agents.

The existing `schedule show`, `schedule install --time HH:MM`, and unqualified `schedule remove` commands remain compatibility aliases for a schedule with ID `default`. The default time remains `07:00`.

## Native backends and identity

- Windows creates one current-user Scheduled Task per enabled entry through `schtasks.exe`.
- macOS creates one per-user LaunchAgent property list per enabled entry and loads it through `launchctl`.
- Linux creates one marked user crontab entry per enabled entry.

Every artifact name or marker contains both a digest of the resolved workspace configuration path and the schedule ID. Reconciliation creates or updates enabled configured entries, removes disabled entries, and removes stale OPMLark-managed entries for that workspace. It never modifies unmarked tasks belonging to the user or another application.

`schedule list` reports configuration. `schedule status` compares desired configuration with native state. `schedule apply` reports every created, updated, removed, unchanged, or failed item. If applying an edited configuration fails, the desired entry remains in configuration and status exposes the drift so the operation can be retried.

## Reliability and safety

The importer uses a workspace-scoped non-blocking run lock. If two schedules overlap, the later invocation exits cleanly without running a second importer against the same SQLite database or article directory.

Native invocations always use a resolved `config.toml` path and a stable globally installed `opmlark` executable. Temporary npx cache paths remain rejected for durable schedules. Scheduler output appends to the workspace scheduler log.

Missed-run behavior differs among native schedulers and is not normalized. Normal ingestion remains resilient because its lookback window discovers eligible articles on the next successful run. One-time jobs follow the native backend's availability behavior.

## Validation and errors

Configuration loading rejects duplicate or invalid IDs, malformed times and dates, unknown recurrence types, missing recurrence fields, extra recurrence fields, empty weekday lists, duplicate weekdays, and calendar values outside their documented ranges. Mutations validate a complete proposed configuration before writing it.

Removal deletes the native artifact before removing configuration, preventing an unmanaged task from being orphaned after a backend failure. Disablement preserves configuration while removing its native projection. OPMLark uses atomic replacement when writing configuration or launchd property lists.

## Testing

Tests cover parsing and validation for every recurrence, configuration mutation round trips, stable per-workspace/per-schedule identities, translation into Windows arguments, macOS LaunchAgent property lists, and Linux cron fields. Reconciliation tests cover multiple entries, disabled schedules, stale managed entries, unrelated native tasks, partial backend failures, compatibility aliases, JSON output, the TUI workflow, and overlapping-run locking.

Platform-specific integration tests inspect native artifacts when running on that platform and skip without failure elsewhere. The full Python suite, Node launcher tests, smoke command, and package dry run remain release gates.
