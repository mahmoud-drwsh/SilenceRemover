[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("QSV", "AMF", "X265")]
    [string]$Encoder
)

$ErrorActionPreference = "Stop"

$inputDir = Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "raw"
$outputDir = Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "output"

Write-Host "Starting vertical video processing with encoder: $Encoder" -ForegroundColor Green

& uv run python (Join-Path $PSScriptRoot ".." "main.py") `
    --input $inputDir `
    --output $outputDir `
    --encoder $Encoder `
    --target-length 178 `
    --noise-threshold -35 `
    --min-duration 0.3

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Vertical video processing completed successfully!" -ForegroundColor Green
