# One run of the Family Deal Finder on this PC. Log: data\local-run.log
param([string]$Python = "python")

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force "data" | Out-Null
$log = Join-Path $PSScriptRoot "data\local-run.log"
function Log { process { "$_" | Out-File -FilePath $log -Append -Encoding utf8 } }

"==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Log
& $Python -m trips.run 2>&1 | Log
"exit code: $LASTEXITCODE" | Log

# Publish only when a GitHub remote has been set up.
if (git remote) {
    git add docs/data.json 2>&1 | Log
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd HH:mm') local run" 2>&1 | Log
        git pull --rebase 2>&1 | Log
        git push 2>&1 | Log
    }
}
"==== finished $(Get-Date -Format 'HH:mm:ss') ====" | Log
