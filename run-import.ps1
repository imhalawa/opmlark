[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$projectRoot = Split-Path -Parent $PSCommandPath
$npmBin = Join-Path $env:APPDATA 'npm'
if (Test-Path (Join-Path $npmBin 'defuddle.cmd')) {
    $env:PATH = "$npmBin;$env:PATH"
}
& python (Join-Path $projectRoot 'fetch_articles.py') @Arguments
exit $LASTEXITCODE
