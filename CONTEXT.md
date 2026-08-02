# Article Collection

This context describes a local reading collection built automatically from subscribed publications. The collection remains useful for reading, annotation, and querying without requiring AI.

## Language

**Catalog**:
An OPML document containing related feed subscriptions and their categories.

**Category**:
A named group within a catalog. Categories may be nested.

**Feed**:
A subscription endpoint that publishes entries which may become articles.
_Avoid_: Source

**Article**:
A preserved, readable copy of a published item. It remains independent from later AI interpretations or summaries.

**Collection**:
The durable set of articles available for reading, annotation, and querying.

**Ingestion**:
The deterministic, token-free process that discovers and collects new articles.
_Avoid_: Enrichment, summarization

**Enrichment**:
An optional AI operation performed on selected articles at the reader's request. Its output is ephemeral and is not part of the managed collection.
_Avoid_: Ingestion
