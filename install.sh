#!/usr/bin/env sh
set -eu

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required. Install Node.js, then run this script again." >&2
  exit 1
fi

npm install --global opmlark
echo 'Installed OPMLark. Run `opmlark init` in a new folder to begin.'
