# Security policy

Please report vulnerabilities privately through GitHub's security advisory form after the repository is published. Do not open a public issue for an unpatched vulnerability.

OPMLark fetches URLs selected by the user, executes the locally installed Defuddle CLI, and writes inside the configured output directory. Treat OPML catalogs from untrusted parties as configuration that should be reviewed before ingestion.
