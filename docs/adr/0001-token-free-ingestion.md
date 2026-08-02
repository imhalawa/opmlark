# Keep ingestion deterministic and token-free

OPMLark discovers feed entries, extracts readable content, writes Markdown, and updates operational state without invoking AI. AI enrichment is an optional downstream activity over articles selected from the collection, so routine monitoring has predictable cost and the collection remains useful without an AI provider.
