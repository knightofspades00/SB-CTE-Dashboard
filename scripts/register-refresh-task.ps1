<#
.SYNOPSIS
  Register (or remove) the daily "Pathways to Positions" hiring refresh as a
  Windows Scheduled Task.

.DESCRIPTION
  The dashboard's green "Hiring now" pills are driven by
  services/refresh_postings.py, which scrapes the SB County jobs portal once
  per day. This script registers that script with Windows Task Scheduler so
  the refresh runs unattended on a schedule (default 6 AM local time).

  Run from PowerShell (no admin required for the default per-user task):
      pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1
      pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1 -Time 07:30
      pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1 -Remove

.PARAMETER Time
  HH:mm to run daily. Defaults to 06:00.

.PARAMETER Remove
  Unregister the task instead of creating it.

.PARAMETER TaskName
  Override the registered task name. Defaults to "Pathways-to-Positions-Refresh".

.NOTES
  Logs are written to scripts/refresh.log (overwritten each run).
#>

[CmdletBinding()]
param(
    [string] $Time     = "06:00",
    [switch] $Remove,
    [string] $TaskName = "Pathways-to-Positions-Refresh"
)

# Resolve project root (one level up from this script).
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    } else {
        Write-Host "No task named '$TaskName' was registered." -ForegroundColor Yellow
    }
    return
}

# Find python.exe — first try the activated venv, then PATH.
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
    else {
        Write-Error "Could not find python.exe (looked in venv/Scripts and PATH). Create a venv or install Python before registering the task."
        exit 1
    }
}

$RefreshScript = Join-Path $ProjectRoot "services\refresh_postings.py"
if (-not (Test-Path $RefreshScript)) {
    Write-Error "Refresh script not found at $RefreshScript."
    exit 1
}

$LogFile = Join-Path $ScriptDir "refresh.log"

# Build the action: cd to project root, run the refresh, redirect output.
$ActionArgs = "/c cd /d `"$ProjectRoot`" && `"$Python`" `"$RefreshScript`" > `"$LogFile`" 2>&1"

$Action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $ActionArgs
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 30)

# Re-register if already present.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Daily refresh of the Pathways to Positions hiring overlay (scrapes governmentjobs.com/careers/sanbernardino)." `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  Runs daily at $Time"
Write-Host "  Python   : $Python"
Write-Host "  Script   : $RefreshScript"
Write-Host "  Log file : $LogFile"
Write-Host ""
Write-Host "Run it once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "Remove later with:"
Write-Host "  pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1 -Remove"
