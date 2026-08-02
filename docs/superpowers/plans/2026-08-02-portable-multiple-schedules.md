# Portable Multiple Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each OPMLark workspace define and manage any number of portable daily, weekly, monthly, or one-time ingestion schedules across Windows, macOS, and Linux.

**Architecture:** `config.toml` remains authoritative. Immutable schedule values are parsed by `configuration.py`, edited atomically through a focused `schedule_config.py` module, and projected by native backend functions in `scheduling.py`; the CLI and TUI call those same services. A separate standard-library run lock prevents overlapping scheduled imports.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `tomllib`, `plistlib`, `subprocess`, `msvcrt`/`fcntl`), Windows Task Scheduler, macOS launchd, Linux crontab, `unittest`, Node.js npm launcher.

## Global Constraints

- Keep `07:00` only as the compatibility default schedule time.
- Support any number of schedule IDs using lowercase letters, numbers, and hyphens.
- Support only portable `daily`, `weekly`, `monthly`, and `once` recurrences; do not expose raw cron.
- Interpret dates and times in the host's local timezone.
- Use only the Python standard library and retain Python 3.11 support.
- Preserve existing article bodies, SQLite ingestion behavior, OPML authority, and AI-optional collection.
- Modify only native scheduler artifacts owned and marked by OPMLark.
- Preserve `schedule show`, `schedule install --time`, and unqualified `schedule remove` as aliases for ID `default`.
- Keep all non-interactive schedule operations available through stable `--json` output.

## File structure

- Modify `article_importer/configuration.py`: immutable `Schedule` model and strict TOML parsing.
- Create `article_importer/schedule_config.py`: atomic schedule block add/edit/enable/disable/remove operations.
- Replace `article_importer/scheduling.py`: portable rendering, native discovery, reconciliation, and compatibility wrappers.
- Create `article_importer/run_lock.py`: workspace-scoped non-blocking cross-platform lock.
- Modify `article_importer/cli.py`: schedule command grammar, handlers, interactive fallback, and run locking.
- Modify `article_importer/tui.py`: schedule list/add/edit/enable/disable/remove/apply/status menu.
- Modify `README.md`, `CONTEXT.md`, and `CHANGELOG.md`: public behavior, examples, and migration notes.
- Modify `tests/test_parsing.py`, `tests/test_scheduling.py`, `tests/test_workspace.py`, and create `tests/test_run_lock.py`: model, translation, reconciliation, CLI, and locking coverage.

---

### Task 1: Portable schedule model and configuration mutations

**Files:**
- Modify: `article_importer/configuration.py`
- Create: `article_importer/schedule_config.py`
- Modify: `tests/test_parsing.py`
- Create: `tests/test_schedule_config.py`

**Interfaces:**
- Produces: `Schedule(id: str, frequency: str, at: str, enabled: bool = True, days: tuple[str, ...] = (), day: int | None = None, date: str | None = None)`.
- Produces: `ImporterConfig.schedules: tuple[Schedule, ...]`.
- Produces: `list_schedule_config(config_path)`, `add_schedule_config(config_path, schedule)`, `edit_schedule_config(config_path, schedule_id, replacement)`, `set_schedule_enabled(config_path, schedule_id, enabled)`, and `remove_schedule_config(config_path, schedule_id)`.

- [ ] **Step 1: Write failing parser tests**

Add table-driven tests that load valid daily, weekly, monthly, and once blocks and reject duplicate IDs, invalid IDs, invalid `HH:MM`, invalid ISO dates, unknown or extra keys, missing recurrence fields, duplicate/empty weekdays, and days outside 1-31. A representative assertion is:

```python
self.assertEqual(
    Schedule("weekend", "weekly", "09:30", days=("sat", "sun")),
    load_config(config).schedules[0],
)
```

- [ ] **Step 2: Run parser tests and verify red**

Run: `python -m unittest tests.test_parsing -v`

Expected: FAIL because `Schedule` and `ImporterConfig.schedules` do not exist.

- [ ] **Step 3: Implement strict schedule parsing**

Add the immutable model, an allowed ID regex, weekday normalization, strict key sets per recurrence, `datetime.date.fromisoformat`, and existing default compatibility:

```python
@dataclass(frozen=True)
class Schedule:
    id: str
    frequency: str
    at: str
    enabled: bool = True
    days: tuple[str, ...] = ()
    day: int | None = None
    date: str | None = None

```

Implement `_read_schedules(config: dict[str, object]) -> tuple[Schedule, ...]`, call it from `load_config`, and retain disabled entries so management commands can see them.

- [ ] **Step 4: Run parser tests and verify green**

Run: `python -m unittest tests.test_parsing -v`

Expected: PASS.

- [ ] **Step 5: Write failing mutation round-trip tests**

Exercise add, full replacement edit, enable/disable, removal, duplicate/unknown IDs, preservation of importer and feed catalog text, and atomic failure behavior. Reload every successful mutation through `load_config`.

- [ ] **Step 6: Run mutation tests and verify red**

Run: `python -m unittest tests.test_schedule_config -v`

Expected: FAIL because `article_importer.schedule_config` does not exist.

- [ ] **Step 7: Implement atomic schedule block mutations**

Serialize one canonical block at a time and atomically replace the config using a same-directory temporary file plus `Path.replace`:

Implement the four exact signatures declared in this task's Interfaces block. Each returns the affected validated `Schedule`; unknown IDs raise `WorkspaceError` and leave the file unchanged.

Validate the complete proposed TOML through `load_config` before replacing the original file.

- [ ] **Step 8: Run focused tests and commit**

Run: `python -m unittest tests.test_parsing tests.test_schedule_config -v`

Expected: PASS.

Commit: `feat: add portable schedule configuration`

---

### Task 2: Native backend rendering and reconciliation

**Files:**
- Modify: `article_importer/scheduling.py`
- Modify: `tests/test_scheduling.py`

**Interfaces:**
- Consumes: `Schedule` and `load_config(config_path).schedules` from Task 1.
- Produces: `ScheduleInfo(id, platform, name, expression, command, enabled)` and `ScheduleChange(id, action, ok, detail)`.
- Produces: `schedule_info(config_path, schedule)`, `schedule_status(config_path)`, `apply_schedules(config_path)`, `remove_native_schedule(config_path, schedule_id)`, plus the legacy `install_schedule` and `remove_schedule` wrappers.

- [ ] **Step 1: Write failing pure-rendering tests**

Cover stable names for two IDs in one workspace, different digests for same-named workspaces, Windows arguments for all four recurrence types, Linux cron fields and markers, macOS plist dictionaries/arrays, quoting paths with spaces, one-time year guards on cron/launchd, and rejection of temporary npx executables.

```python
arguments = windows_create_arguments(info, schedule)
self.assertEqual("WEEKLY", arguments[arguments.index("/SC") + 1])
self.assertEqual("SAT,SUN", arguments[arguments.index("/D") + 1])
```

- [ ] **Step 2: Run renderer tests and verify red**

Run: `python -m unittest tests.test_scheduling.SchedulingRenderingTests -v`

Expected: FAIL because multi-schedule renderers do not exist.

- [ ] **Step 3: Implement native renderers**

Use a workspace digest plus sanitized schedule ID for all names. Render:

- Windows `DAILY`, `WEEKLY`, `MONTHLY`, or `ONCE` arguments.
- Linux five-field cron lines with `# opmlark:<workspace>:<id>` markers.
- macOS LaunchAgent plists under `~/Library/LaunchAgents/io.opmlark.<workspace>.<id>.plist` using `StartCalendarInterval` dictionaries.

For Linux and macOS one-time jobs, wrap the command in an exact local-year/date guard so the calendar trigger cannot import again in a later year.

- [ ] **Step 4: Run renderer tests and verify green**

Run: `python -m unittest tests.test_scheduling.SchedulingRenderingTests -v`

Expected: PASS.

- [ ] **Step 5: Write failing reconciliation tests**

Mock native discovery and subprocesses. Verify apply creates or updates all enabled schedules, removes disabled and stale marked schedules, preserves unrelated native artifacts, reports per-entry partial failures, and status distinguishes `installed`, `missing`, `disabled`, `stale`, and `drifted`.

- [ ] **Step 6: Run reconciliation tests and verify red**

Run: `python -m unittest tests.test_scheduling.SchedulingReconciliationTests -v`

Expected: FAIL because reconciliation functions do not exist.

- [ ] **Step 7: Implement backend discovery and reconciliation**

Keep native effects behind small private functions so tests never mutate the developer's scheduler:

Implement `apply_schedules(config_path)`, `schedule_status(config_path)`, and the three private discovery functions with the exact return types declared in this task's Interfaces block.

Write launchd plists atomically, use per-user `launchctl bootout/bootstrap`, rewrite only OPMLark-marked cron lines, and invoke `schtasks.exe` with argument arrays. Aggregate failures instead of aborting before later schedules are reconciled.

- [ ] **Step 8: Preserve compatibility wrappers**

Make `install_schedule(config_path, time)` add or edit the `default` daily configuration and apply it. Make unqualified `remove_schedule(config_path)` remove the native `default` artifact before its configuration block. Keep `schedule_info(config_path, time)` callable by existing integrations.

- [ ] **Step 9: Run scheduler tests and commit**

Run: `python -m unittest tests.test_scheduling -v`

Expected: PASS.

Commit: `feat: reconcile schedules across operating systems`

---

### Task 3: CLI and TUI schedule management

**Files:**
- Modify: `article_importer/cli.py`
- Modify: `article_importer/tui.py`
- Modify: `tests/test_workspace.py`
- Modify: `tests/test_tui.py`

**Interfaces:**
- Consumes: configuration mutation and native reconciliation functions from Tasks 1-2.
- Produces: `schedule list|add|edit|enable|disable|remove|apply|status` command handlers and an interactive recurrence wizard.

- [ ] **Step 1: Write failing CLI tests**

Test explicit daily, weekly, monthly, and once additions; edit and state changes; ID-specific removal ordering; apply/status result shapes; stable JSON; invalid option combinations; and compatibility aliases. Example:

```python
result = main(["schedule", "add", "weekend", "--weekly", "sat,sun", "--at", "09:30", "--config", str(config), "--json"])
self.assertEqual(0, result)
self.assertEqual(("sat", "sun"), load_config(config).schedules[0].days)
```

- [ ] **Step 2: Run CLI tests and verify red**

Run: `python -m unittest tests.test_workspace -v`

Expected: FAIL because the new subcommands do not exist.

- [ ] **Step 3: Implement CLI grammar and handlers**

Use mutually exclusive recurrence flags:

```text
--daily
--weekly mon,wed,fri
--monthly 15
--once 2026-09-15
--at HH:MM
```

When required values are absent and both standard streams are terminals, prompt one field at a time. In non-interactive mode, return a concise validation error. Emit lists of dataclasses through the existing JSON encoder.

- [ ] **Step 4: Run CLI tests and verify green**

Run: `python -m unittest tests.test_workspace -v`

Expected: PASS.

- [ ] **Step 5: Write failing TUI workflow tests**

Patch `_prompt` and `main` to prove the menu can list, add, edit, enable, disable, remove, apply, and inspect status without performing native mutations.

- [ ] **Step 6: Run TUI tests and verify red**

Run: `python -m unittest tests.test_tui -v`

Expected: FAIL because the schedule management menu is incomplete.

- [ ] **Step 7: Implement the TUI schedule menu**

Replace the three legacy schedule choices with a schedule submenu. Reuse the CLI option vocabulary and display the recurrence choices `daily`, `weekly`, `monthly`, and `once`; do not duplicate configuration or backend logic in `tui.py`.

- [ ] **Step 8: Run focused tests and commit**

Run: `python -m unittest tests.test_workspace tests.test_tui -v`

Expected: PASS.

Commit: `feat: manage multiple schedules from cli and tui`

---

### Task 4: Overlap lock, documentation, and release verification

**Files:**
- Create: `article_importer/run_lock.py`
- Modify: `article_importer/cli.py`
- Create: `tests/test_run_lock.py`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `CHANGELOG.md`
- Modify: `package.json`
- Modify: `pyproject.toml`
- Modify: `article_importer/__init__.py`

**Interfaces:**
- Produces: `RunLock(path: Path)` context manager with `acquired: bool`.
- Changes `opmlark run` to return success with `{"ok": true, "skipped": "already_running"}` when another run holds the workspace lock.

- [ ] **Step 1: Write failing lock tests**

Acquire two locks for the same path in one process and assert only the first succeeds; release and reacquire; verify different workspaces do not contend. Patch `_run` dependencies and assert a skipped overlap performs no feed parsing or database work.

- [ ] **Step 2: Run lock tests and verify red**

Run: `python -m unittest tests.test_run_lock -v`

Expected: FAIL because `RunLock` does not exist.

- [ ] **Step 3: Implement the standard-library lock**

Create the lock file under `data/import.lock`, keep its handle open for the context lifetime, and use non-blocking `msvcrt.locking` on Windows or `fcntl.flock` on Unix. Release in `__exit__` even when ingestion raises.

- [ ] **Step 4: Integrate the lock and verify green**

Run: `python -m unittest tests.test_run_lock -v`

Expected: PASS.

- [ ] **Step 5: Update user documentation and versions**

Document configuration examples, all management commands, interactive use, native backend mapping, local-time and missed-run semantics, default alias migration, JSON examples, and overlapping-run behavior. Add release notes and bump npm/Python/module versions together to `0.2.0`.

- [ ] **Step 6: Run the full local release gate**

Run:

```powershell
python -m unittest discover -v
npm run test:node
npm run smoke
npm pack --dry-run
git diff --check
```

Expected: every command exits 0 and the Python output reports zero failures.

- [ ] **Step 7: Inspect changes against the specification**

Read `docs/superpowers/specs/2026-08-02-portable-multiple-schedules-design.md`, inspect `git diff --stat` and `git diff`, and confirm every requirement has an implementation or explicit test.

- [ ] **Step 8: Commit the completed feature**

Commit: `feat: prevent overlapping scheduled imports`

- [ ] **Step 9: Push and validate CI before release**

Push the feature branch, create or update the concise pull request, wait for all Windows/macOS/Linux CI jobs, merge after success, tag `v0.2.0`, and verify the GitHub release. Publish npm only after `NPM_TOKEN` is a granular automation token with read/write access and bypass-2FA enabled.

## Plan self-review

- Spec coverage: Task 1 covers portable configuration and validation; Task 2 covers all three native backends, identities, drift, safety, and compatibility; Task 3 covers human and machine management; Task 4 covers overlap safety, documentation, packaging, and release gates.
- Placeholder scan: no open-ended marker, deferred implementation instruction, or unspecified error-handling step remains.
- Type consistency: all later tasks consume the exact `Schedule`, `ScheduleInfo`, `ScheduleChange`, configuration mutation, reconciliation, and `RunLock` interfaces introduced earlier.
