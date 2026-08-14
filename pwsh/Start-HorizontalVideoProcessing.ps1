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
    "--local-title-and-trim-only"
)

# Horizontal processing remains local. main.py loads .env, so an absent
# variable would be restored there; an explicit empty value survives dotenv.
# The horizontal mode additionally excludes subtitles, overlays, companion
# outputs, and all Media Manager uploads.
$hadMediaManagerUrl = Test-Path Env:MEDIA_MANAGER_URL
$previousMediaManagerUrl = $env:MEDIA_MANAGER_URL
$env:MEDIA_MANAGER_URL = ""
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
