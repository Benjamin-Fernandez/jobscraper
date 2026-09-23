# JobScraper launcher.
#   .\run.ps1            process the next 30 companies
#   .\run.ps1 status     where the cursor is
#   .\run.ps1 doctor     check setup, incl. which judge transport is live
#   .\run.ps1 view       browse all matches, tick off applications
#   .\run.ps1 run --force
#   .\run.ps1 -NoView    run the batch without opening the viewer
#
# Judging goes through Claude Code (`claude -p`) by default - no API key.
# To judge inside a Claude Code session instead:
#   .\run.ps1 review --export     then ask Claude Code to fill review_verdicts.json
#   .\run.ps1 review --apply
[CmdletBinding()]
param(
    [switch]$NoView,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$env:PYTHONIOENCODING = "utf-8"

if (-not $CliArgs -or $CliArgs.Count -eq 0) { $CliArgs = @("run") }

python -m jobscraper @CliArgs
$code = $LASTEXITCODE

# After a successful run, hand straight over to the viewer: it serves the match
# page so the Applied ticks can write back to the tracker. Ctrl+C stops it.
if ($code -eq 0 -and $CliArgs[0] -eq "run" -and -not $NoView) {
    Write-Host ""
    Write-Host "Starting the viewer - tick 'Applied' and the tracker updates." -ForegroundColor Cyan
    python -m jobscraper view
    $code = $LASTEXITCODE
}
exit $code
