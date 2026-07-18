# Rolling Three-Month Feed Lookback

## Purpose

Replace the initial no-backfill-only subscription behavior with a rolling 90-day import window. Every daily run must import eligible, not-yet-imported articles from the prior three months while preserving URL-level deduplication.

## Configuration

Add `lookback_days = 90` under `[importer]` in `config.toml`. The cutoff is calculated from the run time in UTC.

## Eligibility

- An entry with a parsed RSS/Atom publication or update time is eligible when its timestamp is on or after the cutoff.
- An entry without a usable timestamp receives the observation time as its effective timestamp and is eligible on first observation.
- Entries older than the cutoff are recorded as `seeded` and are never fetched unless they become eligible through a future explicit policy change.
- The logic applies equally to existing and newly added feeds.

## State behavior

For a newly seen feed, record every visible entry. Entries inside the window become candidates immediately; older entries are seeded. For an existing feed, previously seeded entries are reconsidered whenever their stored/effective date is inside the current window. Successful imports become `imported` and remain excluded. Failed entries continue to retry while visible and eligible. SQLite remains the authoritative deduplication store.

## Notes

Defuddle output remains unchanged after generated frontmatter. Add `publication_date_source` to frontmatter with `feed` for a feed-provided timestamp and `observed` for the observation-time fallback. All generated notes retain `ingested_by: opml-defuddle-articles`.

## Error handling and verification

Undated entries use the observation fallback rather than failing or expanding the window. Tests must cover: new-feed in-window versus old entry handling; existing seeded in-window promotion; imported URL exclusion; failed-entry retry; undated observation fallback; and frontmatter provenance. A live run after deployment should import eligible items from the visible feed windows only, with SQLite preventing duplicates on later runs.
