[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("QSV", "AMF", "X265")]
    [string]$Encoder
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonCandidates = @(
    (Join-Path $repoRoot ".venv" "Scripts" "python.exe"),
    (Join-Path $repoRoot "venv" "Scripts" "python.exe")
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $pythonExe) {
    $searched = $pythonCandidates -join ", "
    throw "Could not find project Python executable. Checked: $searched"
}

& $pythonExe `
    (Join-Path $repoRoot "main.py") `
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
