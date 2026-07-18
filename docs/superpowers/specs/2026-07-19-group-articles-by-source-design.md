# Group Articles by Source Design

## Goal

Organize every existing and future article note beneath `Sources/Articles/<source>/`.

## Folder naming

- Importer-created notes use their frontmatter `feed` value, sanitized for Windows directory names (for example, `ByteByteGo` and `High Scalability`).
- Legacy notes without a `feed` property use the hostname from their `source` URL (for example, `stephango.com`).
- Notes with neither usable property go to `Unknown Source`.

## Move behavior

The migration scans only Markdown files directly under `Sources/Articles`, creates target folders as needed, and moves each note without changing its bytes. If a target filename already exists, it uses the importer’s numbered-name convention. The operation is idempotent: notes already under a source folder are skipped.

## Future imports and state

`create_note` receives the source folder and writes there from the outset. Existing SQLite output paths are updated during the move so recovery finds the relocated note. The active archive process must be paused before moving files and resumed afterward; state-based URL deduplication makes resumption safe.

## Validation

Tests cover feed and hostname folder selection, byte-preserving moves, collision handling, idempotence, and state-path updates. A live migration checks that no Markdown files remain at the Articles root and that the archive process resumes.
