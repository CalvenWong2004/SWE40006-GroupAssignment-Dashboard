<#
.SYNOPSIS
  Starts the GitHub Actions runner automatically when you sign in to Windows.

.DESCRIPTION
  Creates a scheduled task ("GitHubActionsRunner") that runs the runner's run.cmd, hidden, one minute
  after you sign in, as YOUR user (so it can reach Docker Desktop and kubectl). If the runner stops,
  Windows restarts it.

  Run once, in a normal (non-administrator) PowerShell window:
      powershell -ExecutionPolicy Bypass -File .\scripts\install-runner-autostart.ps1

  Prerequisites (this script does not do them):
    * The runner is already configured in the runner folder (config.cmd ran successfully).
    * Docker Desktop is set to start at sign-in:
      Docker Desktop -> Settings -> General -> "Start Docker Desktop when you sign in".
    * The PC is on and signed in. This is not a Windows service, so it does not run at the lock
      screen before sign-in or while signed out.

.PARAMETER RunnerPath
  Folder where the runner is installed. Default: C:\actions-runner

.PARAMETER StartNow
  Also start the task now (stops a runner you started by hand first, or it would conflict).

.PARAMETER Remove
  Remove the scheduled task instead of creating it.
#>
[CmdletBinding()]
param(
    [string]$RunnerPath = 'C:\actions-runner',
    [switch]$StartNow,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'GitHubActionsRunner'

function Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "!!  $Message" -ForegroundColor Yellow }
function Ok([string]$Message)   { Write-Host "OK  $Message" -ForegroundColor Green }

try {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    if ($Remove) {
        if ($existing) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Ok "Removed scheduled task '$taskName'"
        } else {
            Warn "No scheduled task named '$taskName' exists."
        }
        return
    }

    # ---- checks
    if (-not (Test-Path -LiteralPath (Join-Path $RunnerPath 'run.cmd'))) {
        throw "run.cmd was not found in '$RunnerPath'. Pass -RunnerPath <folder> if the runner is installed elsewhere."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RunnerPath '.runner'))) {
        throw "The runner in '$RunnerPath' is not configured yet. Run config.cmd first (with --labels docker-desktop)."
    }

    $running = Get-Process -Name 'Runner.Listener' -ErrorAction SilentlyContinue
    if ($running -and -not $StartNow) {
        Warn 'A runner is running right now (started by hand). The task will start at your next sign-in.'
        Warn 'Close that window before then, or use -StartNow to hand over to the task.'
    }

    # ---- create or replace the task
    $command = "Set-Location -LiteralPath '$RunnerPath'; & .\run.cmd"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -WindowStyle Hidden -Command "{0}"' -f $command) `
        -WorkingDirectory $RunnerPath

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = 'PT1M'   # give Docker Desktop a minute before the runner comes online

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1)

    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Info "Replacing the existing '$taskName' task"
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description 'Starts the GitHub Actions self-hosted runner at sign-in' | Out-Null
    Ok "Created scheduled task '$taskName' (runs at sign-in as $env:USERNAME, hidden)"

    if ($StartNow) {
        if ($running) {
            Info 'Stopping the runner that was started by hand'
            $running | Stop-Process -Force
            Start-Sleep -Seconds 3
        }
        Start-ScheduledTask -TaskName $taskName
        Ok 'Started the task. The runner should show as Idle on GitHub in about 30 seconds.'
    }

    Write-Host ''
    Write-Host 'Next:' -ForegroundColor Green
    Write-Host '  * Check: repo Settings -> Actions -> Runners should show the runner Idle with the docker-desktop label.'
    Write-Host '  * Make sure Docker Desktop starts at sign-in (Settings -> General).'
    Write-Host '  * Runner logs, if needed: ' (Join-Path $RunnerPath '_diag')
    Write-Host "  * Stop it:    Stop-ScheduledTask -TaskName $taskName"
    Write-Host "  * Remove it:  powershell -ExecutionPolicy Bypass -File .\scripts\install-runner-autostart.ps1 -Remove"
}
catch {
    Write-Host ''
    Write-Host "XX  $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
