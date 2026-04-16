$ErrorActionPreference = "Stop"

$homeDir = $HOME
$inputDir = Join-Path $homeDir "Videos\Vertical\raw"

if (-not (Test-Path $inputDir)) {
    Write-Error "Input directory not found. Expected: $inputDir"
    exit 1
}

& uv run main.py $inputDir --encoder QSV --target-length 178 --noise-threshold -40 --min-duration 0.3 --enable-media-manager --enable-title-overlay --enable-logo-overlay

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Vertical video processing completed successfully!" -ForegroundColor Green
