export function isSupportedPythonVersion(versionText) {
  const match = versionText.match(/Python\s+(\d+)\.(\d+)/i);
  return Boolean(
    match &&
      (Number(match[1]) > 3 ||
        (Number(match[1]) === 3 && Number(match[2]) >= 11)),
  );
}
