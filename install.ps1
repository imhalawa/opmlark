[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js and npm are required. Install Node.js, then run this script again.'
}
npm install --global opmlark
Write-Host 'Installed OPMLark. Run `opmlark init` in a new folder to begin.'
