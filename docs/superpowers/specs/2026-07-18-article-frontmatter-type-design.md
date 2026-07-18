# Article Frontmatter Type Design

## Goal

Classify every importer-created article note with the Obsidian property `type: article`.

## Scope

- New notes receive `type: article` in their generated YAML frontmatter.
- A migration scans only `Sources/Articles/*.md` notes carrying `ingested_by: opml-defuddle-articles` and inserts the property when absent.
- The migration preserves the article body byte-for-byte and is idempotent.
- Notes without the importer marker, and notes already carrying a `type` property, are unchanged.

## Design

`build_frontmatter` emits `type: article` before the title. A CLI flag performs the explicit migration after loading the configured vault. It changes only the YAML prefix ending at the first frontmatter delimiter, inserting the property immediately after the opening delimiter. The command reports how many notes it updated.

## Validation

Unit tests assert generated metadata contains the property and that migration updates a marked note while preserving its body, leaving unmarked and already-typed notes unchanged. The full suite verifies the integration.
