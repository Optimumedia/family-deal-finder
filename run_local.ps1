# One run of the Family Deal Finder on this PC.
# Log: data\logs\run-YYYY-MM-DD.log (one file per day, kept 30 days).
# Exit code: 0 = fine, 3 = ran but a source failed (see docs\health.json; data still published),
#            4 = another run was still going (skipped), 5 = git pull failed, 6 = commit failed,
#            7 = push failed, other = python's own exit code (the run crashed; see the log).
param([string]$Python = "python", [int]$KeepLogDays = 30)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$logDir = Join-Path $PSScriptRoot "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "run-$(Get-Date -Format 'yyyy-MM-dd').log"
function Log { process { "$_" | Out-File -FilePath $log -Append -Encoding utf8 } }

# Rotation: drop daily logs older than $KeepLogDays, and the old single log once it is that old.
$cutoff = (Get-Date).AddDays(-$KeepLogDays)
Get-ChildItem $logDir -Filter "run-*.log" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force -ErrorAction SilentlyContinue
$oldLog = Join-Path $PSScriptRoot "data\local-run.log"
if ((Test-Path $oldLog) -and (Get-Item $oldLog).LastWriteTime -lt $cutoff) { Remove-Item $oldLog -Force }

# Lock: an open file handle nobody else may share. Windows releases it even if this script
# is killed, so a crash never leaves a stale lock behind.
$lockPath = Join-Path $PSScriptRoot "data\run.lock"
try {
    $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') skipped: another run still holds data\run.lock ====" | Log
    exit 4
}

function Invoke-Run {
    "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Log
    & $Python -m trips.run 2>&1 | Log
    $pyExit = $LASTEXITCODE
    "python exit code: $pyExit" | Log
    # 3 = some source failed but the run finished: publish what we have. Anything else: stop.
    if ($pyExit -ne 0 -and $pyExit -ne 3) { "run failed, nothing published" | Log; return $pyExit }

    # Publish only when a GitHub remote has been set up.
    if (-not (git remote)) { "no git remote: not publishing" | Log; return $pyExit }

    # Skip the commit when only the "generated" timestamp changed. (No quote characters in the
    # pattern: Windows PowerShell 5.1 mangles quotes inside native-command arguments.)
    git diff --quiet '--ignore-matching-lines=^ *.generated.: ' -- docs/data.json
    if ($LASTEXITCODE -eq 0) { "data.json unchanged (apart from its timestamp): no commit" | Log; return $pyExit }

    git pull --rebase --autostash 2>&1 | Log
    if ($LASTEXITCODE -ne 0) {
        "git pull --rebase failed (exit $LASTEXITCODE): aborting the rebase, not committing" | Log
        git rebase --abort 2>&1 | Log
        return 5
    }
    $files = @("docs/data.json")
    if (Test-Path "docs/health.json") { $files += "docs/health.json" }
    git add -- $files 2>&1 | Log
    # Commit only these paths, even if something else happens to be staged.
    git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd HH:mm') local run" -- $files 2>&1 | Log
    if ($LASTEXITCODE -ne 0) { "git commit failed (exit $LASTEXITCODE)" | Log; return 6 }
    git push 2>&1 | Log
    if ($LASTEXITCODE -ne 0) { "git push failed (exit $LASTEXITCODE): it goes out with the next run" | Log; return 7 }
    return $pyExit
}

$exit = 1
try {
    $exit = [int](Invoke-Run | Select-Object -Last 1)
} finally {
    "==== finished $(Get-Date -Format 'HH:mm:ss'), exit $exit ====" | Log
    $lock.Dispose()
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
exit $exit
