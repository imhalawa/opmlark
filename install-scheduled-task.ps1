[CmdletBinding()]
param()

$projectRoot = Split-Path -Parent $PSCommandPath
$runner = Join-Path $projectRoot 'run-import.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $runner)
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'OPML Defuddle Articles' -Action $action -Trigger $trigger -Settings $settings -Description 'Imports new OPML feed articles through Defuddle.' -Force | Out-Null
