# Modular Topic Feed Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support configurable topic OPML catalogs, source controls, storage folders, and the requested expanded feeds.

**Architecture:** Parse catalog declarations from TOML, pass catalog defaults to OPML parsing, and carry source ID/storage folder in `FeedSubscription`. Source folder resolution uses this field before existing fallbacks. Each catalog remains an ordinary editable OPML file.

**Tech Stack:** Python 3 standard library, TOML, XML/OPML, unittest.

## Global Constraints

- Catalog IDs and source IDs are unique among enabled inputs.
- Disable precedence: config disabled catalog/source overrides catalog/source enabled flags.
- Folder overrides are relative to Articles and reject traversal.
- The normal daily schedule loads enabled catalogs only.

---

### Task 1: Catalog configuration and parser

**Files:** `article_importer/configuration.py`, `article_importer/models.py`, `article_importer/parsing.py`, `fetch_articles.py`, tests.

- [ ] Add failing tests for two catalogs, category/source disablement, duplicate source IDs, and catalog folder inheritance.
- [ ] Implement `FeedCatalog` configuration and multi-file `parse_catalogs` aggregation.
- [ ] Run focused parser/configuration tests.

### Task 2: Folder override and catalog validation

**Files:** `article_importer/notes.py`, `fetch_articles.py`, tests.

- [ ] Add failing tests for source and catalog storage-folder precedence plus invalid paths.
- [ ] Implement safe relative folder normalization and `--validate-catalogs` endpoint/parser validation.
- [ ] Run focused notes/service tests.

### Task 3: Topic OPML catalogs and documentation

**Files:** `feeds/*.opml`, `config.toml`, `README.md`, tests.

- [ ] Add the requested topic OPML files with verified public sources and stable source IDs.
- [ ] Configure enabled catalogs and source/company folder overrides.
- [ ] Document extension, disablement, folders, and validation.
- [ ] Run the complete suite and endpoint validation.
