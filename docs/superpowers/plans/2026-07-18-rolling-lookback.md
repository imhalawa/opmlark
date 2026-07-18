
# Rolling Three-Month Lookback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import each feed’s unimported entries from the trailing 90 days on every daily run.

**Architecture:** Extend configuration with a UTC lookback duration, then make state selection classify visible entries by an effective timestamp. Feed timestamps are preferred; undated entries receive their first-observation time. Existing SQLite status remains the deduplication authority.

**Tech Stack:** Python 3.11+ standard library, SQLite, Defuddle CLI, `unittest`.

## Global Constraints

- Set `[importer].lookback_days = 90`; calculate the cutoff in UTC.
- Apply the same window to existing and newly added feeds.
- Keep article bodies unchanged after generated frontmatter.
- Keep `ingested_by: opml-defuddle-articles`; add `publication_date_source: feed|observed`.
- Use observation time for entries without a usable feed timestamp.
- Never re-import an `imported` URL; retry failed visible URLs while eligible.
- Preserve project-local SQLite and the daily 07:00 schedule.

---

### Task 1: Add configurable rolling eligibility and provenance

**Files:**

- Modify: `config.toml`
- Modify: `article_importer/configuration.py`
- Modify: `article_importer/models.py`
- Modify: `article_importer/state.py`
- Modify: `article_importer/notes.py`
- Modify: `article_importer/service.py`
- Modify: `tests/test_parsing.py`
- Modify: `tests/test_state.py`
- Modify: `tests/test_notes.py`
- Modify: `tests/test_service.py`
- Modify: `README.md`

**Interfaces:**

- `ImporterConfig` gains `lookback_days: int`.
- `FeedEntry` gains `publication_date_source: Literal["feed", "observed"]`.
- `StateStore.candidates(subscription, entries, cutoff, observed_at, dry_run=False) -> FeedBatch`.
- `build_frontmatter()` writes the entry’s publication date source.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_new_feed_imports_only_entries_inside_the_90_day_window(self) -> None:
    cutoff = datetime(2026, 4, 19, tzinfo=timezone.utc)
    batch = state.candidates(SUBSCRIPTION, [OLD_ENTRY, RECENT_ENTRY], cutoff, NOW)
    self.assertEqual({RECENT_ENTRY.url}, {entry.url for entry in batch.candidates})
    self.assertEqual(1, batch.seeded)

def test_seeded_recent_entry_is_promoted_on_later_run(self) -> None:
    state.seed_legacy(SUBSCRIPTION, [RECENT_ENTRY])
    batch = state.candidates(SUBSCRIPTION, [RECENT_ENTRY], CUTOFF, NOW)
    self.assertEqual((RECENT_ENTRY,), batch.candidates)

def test_undated_entry_uses_observation_time_and_frontmatter_marks_it(self) -> None:
    batch = state.candidates(SUBSCRIPTION, [UNDATED_ENTRY], CUTOFF, NOW)
    self.assertEqual("observed", batch.candidates[0].publication_date_source)
    frontmatter = build_frontmatter(ARTICLE, batch.candidates[0], NOW)
    self.assertIn("publication_date_source: \"observed\"", frontmatter)
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `python -m unittest tests.test_state tests.test_notes tests.test_parsing -v`

Expected: failures because the current interfaces have no lookback or provenance support.

- [ ] **Step 3: Implement the rolling selection**

Parse `lookback_days` as a positive integer (default is invalid; the checked-in config supplies `90`). At each service run compute:

```python
observed_at = datetime.now(timezone.utc)
cutoff = observed_at - timedelta(days=config.lookback_days)
```

For every visible entry, use its feed timestamp when present; otherwise set `published = observed_at` and `publication_date_source = "observed"`. On a new feed, insert older entries as `seeded`; insert eligible entries as retryable candidates. On an existing feed, return visible `failed` entries and visible `seeded` entries whose stored/effective publication time is on or after cutoff; retain `imported` exclusion. Update frontmatter with `publication_date_source` quoted through the existing YAML scalar encoder. Keep dry-run read-only while reporting eligible candidates.

- [ ] **Step 4: Run focused and complete tests**

Run: `python -m unittest discover -s tests -v`

Expected: all existing tests plus rolling-window, seeded-promotion, undated-fallback, and frontmatter-provenance tests pass.

- [ ] **Step 5: Update configuration and usage documentation**

```toml
[importer]
vault_path = "C:/Users/imhal/Documents/Traces"
defuddle_executable = "defuddle"
lookback_days = 90
```

Update `README.md` to state that every run imports eligible visible entries from the trailing 90 days, including on a newly added feed; older visible entries are seeded. Explain that undated items use the observation time, are marked `publication_date_source: observed`, and are still URL-deduplicated.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
python -B -m unittest discover -s tests -v
git diff --check
```

Expected: no failures and no whitespace errors.

```powershell
git add config.toml README.md article_importer tests
git commit -m "feat: add rolling three-month lookback"
```

## Plan Self-Review

- Spec coverage: one task updates configuration, state selection, undated fallback, note provenance, documentation, and all required tests.
- Placeholder scan: no open implementation placeholders remain.
- Type consistency: `ImporterConfig.lookback_days`, `FeedEntry.publication_date_source`, and the state lookback parameters are defined before service and frontmatter use them.

