import test from "node:test";
import assert from "node:assert/strict";

import { isSupportedPythonVersion } from "../bin/python-version.js";

test("accepts Python 3.11 and later", () => {
  assert.equal(isSupportedPythonVersion("Python 3.11.0"), true);
  assert.equal(isSupportedPythonVersion("Python 3.13.7\r\n"), true);
  assert.equal(isSupportedPythonVersion("Python 4.0.0"), true);
});

test("rejects old and malformed Python versions", () => {
  assert.equal(isSupportedPythonVersion("Python 3.10.14"), false);
  assert.equal(isSupportedPythonVersion("Python 2.7.18"), false);
  assert.equal(isSupportedPythonVersion("not Python"), false);
  assert.equal(isSupportedPythonVersion(""), false);
});
