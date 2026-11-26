# Registers two Windows scheduled tasks (13:00 and 17:30 — the PC is on 12:00–19:00, and these
# don't overlap the property finder's 12:15 / 16:45 runs) that run run_local.ps1.
# Re-run this script any time; it replaces the existing tasks.
# Remove with:  Unregister-ScheduledTask -TaskName "Family Deal Finder*" -Confirm:$false
# "Last Run Result" in Task Scheduler is run_local.ps1's exit code: 0 ok, 3 a source failed
# (docs\health.json says which), 4 skipped (a run was still going), 5/6/7 git pull/commit/push failed.
# Overlaps are stopped twice: IgnoreNew below, and run_local.ps1's own data\run.lock.
# A project venv: scheduled tasks don't always see per-user site-packages.
$venv = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    & (Get-Command python).Source -m venv $venv
}
& "$venv\Scripts\python.exe" -m pip install -q -r (Join-Path $PSScriptRoot "requirements.txt")
$python = "$venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "run_local.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Python `"$python`"" `
    -WorkingDirectory $PSScriptRoot
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

foreach ($t in @(@{Name = "Family Deal Finder - midday"; At = "13:00"}, @{Name = "Family Deal Finder - evening"; At = "17:30"})) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.At
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings `
        -Description "Checks family vacation deals and pushes the dashboard to GitHub Pages." -Force | Out-Null
    Write-Output "registered: $($t.Name) at $($t.At)"
}
