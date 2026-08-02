# Contributing to OPMLark

Thank you for helping make token-free article collection useful to more readers.

## Development setup

1. Install Python 3.11+, Node.js 18+, and npm.
2. Run `npm install` to install Defuddle.
3. Run `python -m unittest discover -v`.
4. Run `npm run smoke` and `npm pack --dry-run`.

Keep OPML as the subscription source of truth, preserve imported Markdown bodies, and add tests for behavior changes. Product language belongs in `CONTEXT.md`; architectural trade-offs that are hard to reverse belong in a short ADR under `docs/adr/`.

Use Conventional Commits for commit messages. Open focused pull requests that explain the user-visible impact and include the checks you ran.
