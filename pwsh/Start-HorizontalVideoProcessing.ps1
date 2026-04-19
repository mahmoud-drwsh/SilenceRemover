$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$homeDir = $HOME
$inputDir = Join-Path $homeDir "Videos\raw"

if (-not (Test-Path $inputDir)) {
    Write-Error "Input directory not found. Expected: $inputDir"
    exit 1
}

& (Join-Path $PSScriptRoot "Move-IgnoredRawVideos.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Raw preflight scan failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

& uv run main.py $inputDir --encoder QSV --noise-threshold -40 --min-duration 1.0 --pad-sec 0.5

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Horizontal video processing completed successfully!" -ForegroundColor Green
