# JobScraper launcher (v2).
#   .\run.ps1              run one batch (the 10 most-overdue companies), then open the web app
#   .\run.ps1 -NoWeb       run the batch without opening the web app
#   .\run.ps1 web          just the web app: Inbox + Applications at http://127.0.0.1:8765
#   .\run.ps1 status       who is due, run cadence, quarantine
#   .\run.ps1 doctor       check setup, incl. which judge transport is live
#   .\run.ps1 watchlist list | add "Name" https://careers.url | disable <key>
#
# Judging goes through Claude Code (`claude -p`) by default - no API key.
# To judge inside a Claude Code session instead:
#   .\run.ps1 review --export     then ask Claude Code to judge data\review_queue.json
#   .\run.ps1 review --apply
[CmdletBinding()]
param(
    [switch]$NoWeb,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$env:PYTHONIOENCODING = "utf-8"

if (-not $CliArgs -or $CliArgs.Count -eq 0) { $CliArgs = @("run") }

python -m jobscraper @CliArgs
$code = $LASTEXITCODE

# After a successful run, open the one page that shows every run: the web app.
# Ctrl+C stops it.
if ($code -eq 0 -and $CliArgs[0] -eq "run" -and -not $NoWeb) {
    Write-Host ""
    Write-Host "Starting the web app - http://127.0.0.1:8765 (Ctrl+C to stop)" -ForegroundColor Cyan
    Start-Process "http://127.0.0.1:8765"
    python -m jobscraper web
    $code = $LASTEXITCODE
}
exit $code
