[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$projectRoot = Split-Path -Parent $PSCommandPath
& python (Join-Path $projectRoot 'fetch_articles.py') @Arguments
exit $LASTEXITCODE
