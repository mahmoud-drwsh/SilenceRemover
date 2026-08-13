$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$homeDir = $HOME
$inputDir = Join-Path $homeDir "Videos\raw"

if (-not (Test-Path $inputDir)) {
    Write-Error "Input directory not found. Expected: $inputDir"
    exit 1
}

$preflightArgs = @(
    "run"
    "python"
    (Join-Path $PSScriptRoot "Move-IgnoredRawVideos.py")
    "--targets"
    "horizontal"
)

& uv @preflightArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Raw preflight scan failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$pipelineArgs = @(
    "run"
    "python"
    "main.py"
    $inputDir
    "--encoder"
    "QSV"
    "--non-target-noise-threshold"
    "-40"
    "--non-target-min-duration"
    "1.0"
    "--non-target-pad-sec"
    "0.5"
)

# Horizontal processing remains local. Only the Vertical launcher is allowed
# to inherit MEDIA_MANAGER_URL and hand Originals to the server worker.
$hadMediaManagerUrl = Test-Path Env:MEDIA_MANAGER_URL
$previousMediaManagerUrl = $env:MEDIA_MANAGER_URL
Remove-Item Env:MEDIA_MANAGER_URL -ErrorAction SilentlyContinue
try {
    & uv @pipelineArgs
    $pipelineExitCode = $LASTEXITCODE
} finally {
    if ($hadMediaManagerUrl) {
        $env:MEDIA_MANAGER_URL = $previousMediaManagerUrl
    } else {
        Remove-Item Env:MEDIA_MANAGER_URL -ErrorAction SilentlyContinue
    }
}

if ($pipelineExitCode -ne 0) {
    Write-Error "Pipeline failed with exit code $pipelineExitCode"
    exit $pipelineExitCode
}

Write-Host "Horizontal video processing completed successfully!" -ForegroundColor Green
