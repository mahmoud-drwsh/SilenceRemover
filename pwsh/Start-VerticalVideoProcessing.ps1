[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("QSV", "AMF", "X265")]
    [string]$Encoder
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot ".." ".." "venv" "Scripts" "python.exe") `
    (Join-Path $PSScriptRoot ".." ".." "main.py") `
    --input (Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "raw") `
    --output (Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "output") `
    --encoder $Encoder `
    --target-length 178 `
    --noise-threshold -35 `
    --min-duration 0.3

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Vertical video processing completed successfully!" -ForegroundColor Green
