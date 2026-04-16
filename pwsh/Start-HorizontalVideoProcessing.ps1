[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("QSV", "AMF", "X265")]
    [string]$Encoder
)

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Location).Path
$pythonExe = Join-Path $repoRoot ".venv" "Scripts" "python.exe"
$mainPy = Join-Path $repoRoot "main.py"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python executable not found in the current directory. Expected: $pythonExe"
    exit 1
}

if (-not (Test-Path $mainPy)) {
    Write-Error "main.py not found in the current directory. Expected: $mainPy"
    exit 1
}

& $pythonExe `
    $mainPy `
    --input (Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "raw") `
    --output (Join-Path $PSScriptRoot ".." ".." ".." "Desktop" "TEMP" "output") `
    --encoder $Encoder `
    --target-length 238 `
    --noise-threshold -35 `
    --min-duration 0.3

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Horizontal video processing completed successfully!" -ForegroundColor Green
