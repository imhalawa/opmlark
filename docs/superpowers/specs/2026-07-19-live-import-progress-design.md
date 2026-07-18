# Live Import Progress Design

The importer will accept an optional progress callback and emit plain, flushed console lines for the start of the run, each feed, each candidate article, article outcomes, and the final summary. The existing file logger remains the durable diagnostic record; progress text does not alter feeds, state, frontmatter, or article bodies.

`fetch_articles.py` will provide the console callback for normal runs and dry runs. The scheduled PowerShell host will therefore show activity immediately, while `run-import.ps1` remains portable and unchanged.
