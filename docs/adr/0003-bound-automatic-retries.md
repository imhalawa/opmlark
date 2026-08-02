# Bound automatic article retries

OPMLark automatically attempts a failed article only up to the workspace's configured `max_attempts`. Exhausted failures remain queryable and may be reset explicitly; this trades automatic eventual ingestion for healthy scheduled runs when a page can never be extracted.
