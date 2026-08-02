#!/usr/bin/env node

import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const localBins = [
  resolve(packageRoot, "node_modules", ".bin"),
  resolve(packageRoot, "..", ".bin"),
];
const env = {
  ...process.env,
  PATH: `${localBins.join(delimiter)}${delimiter}${process.env.PATH ?? ""}`,
  PYTHONPATH: `${packageRoot}${delimiter}${process.env.PYTHONPATH ?? ""}`,
};

const candidates =
  process.platform === "win32"
    ? [
        ["py", ["-3"]],
        ["python", []],
      ]
    : [
        ["python3", []],
        ["python", []],
      ];

let selected;
for (const [command, prefix] of candidates) {
  const check = spawnSync(command, [...prefix, "--version"], {
    env,
    encoding: "utf8",
    windowsHide: true,
  });
  if (check.status === 0) {
    selected = [command, prefix];
    break;
  }
}

if (!selected) {
  console.error("OPMLark requires Python 3.11 or newer. Install Python and try again.");
  process.exit(1);
}

const [python, prefix] = selected;
const result = spawnSync(
  python,
  [...prefix, "-m", "article_importer", ...process.argv.slice(2)],
  { env, stdio: "inherit", windowsHide: false },
);

if (result.error) {
  console.error(`Unable to start OPMLark: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
