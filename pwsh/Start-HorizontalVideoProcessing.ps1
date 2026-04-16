$ErrorActionPreference = "Stop"

& uv run main.py "C:\Users\user\Videos\raw\" --encoder QSV --target-length 178 --noise-threshold -40 --min-duration 0.3

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Horizontal video processing completed successfully!" -ForegroundColor Green
