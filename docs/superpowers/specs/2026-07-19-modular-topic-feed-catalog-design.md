# Modular Topic Feed Catalog Design

## Goal

Replace the single feed OPML with independently editable, topic-focused OPML catalogs and configurable enablement and storage folders.

## Catalog configuration

`config.toml` contains `[[feed_catalogs]]` entries with a stable `id`, path, `enabled` flag, and optional `folder`. The importer loads only enabled catalogs and ignores IDs listed in `[feed_catalog].disabled_catalogs`. `[feed_catalog].disabled_sources` disables matching source IDs across all catalogs.

## OPML source configuration

Every feed outline has a stable `id`. `enabled="false"` disables it locally. Optional `folder` overrides the catalog folder for notes from that source. Precedence is source folder, catalog folder, then the existing feed/hostname folder. Folder paths are relative to Articles and reject absolute paths, empty segments, and traversal.

## Catalog content

Separate OPML files organize System Design and Distributed Systems; Architecture and Microservices; Algorithms and Problem Solving; Interviews; Observability; Company Engineering; Career; Psychology (with ADHD, memory, focus, time, anxiety, sleep); Philosophy; Neuroscience; and Calisthenics. Catalogs include only verified public RSS/Atom sources; sources without public feeds are documented but not scraped automatically.

## Validation

Tests cover multi-file aggregation, catalog/source precedence, duplicate IDs, disable rules, invalid folders, and folder placement. A catalog validation command verifies every enabled feed endpoint parses before the daily scheduler consumes it.
