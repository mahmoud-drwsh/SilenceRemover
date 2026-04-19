$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$homeDir = $HOME
$inputDir = Join-Path $homeDir "Videos\Vertical\raw"

if (-not (Test-Path $inputDir)) {
    Write-Error "Input directory not found. Expected: $inputDir"
    exit 1
}

& uv run python (Join-Path $PSScriptRoot "Move-IgnoredRawVideos.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Raw preflight scan failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

& uv run main.py $inputDir --encoder QSV --target-length 179 --enable-media-manager --enable-title-overlay --enable-logo-overlay

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Vertical video processing completed successfully!" -ForegroundColor Green
