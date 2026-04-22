param(
    [ValidateSet("QSV", "AMF", "X265")]
    [string]$Encoder = "QSV",

    [double]$TitleYFraction = (1.0 / 6.0),

    [double]$TitleHeightFraction = (1.0 / 6.0)
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$homeDir = $HOME
$inputDir = Join-Path $homeDir "Videos\Vertical\raw"

if (-not (Test-Path $inputDir)) {
    Write-Error "Input directory not found. Expected: $inputDir"
    exit 1
}

$preflightArgs = @(
    "run"
    "python"
    (Join-Path $PSScriptRoot "Move-IgnoredRawVideos.py")
    "--targets"
    "vertical"
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
    $Encoder
    "--target-length"
    "179"
    "--enable-media-manager"
    "--enable-title-overlay"
    "--enable-logo-overlay"
    "--title-y-fraction"
    $TitleYFraction.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    "--title-height-fraction"
    $TitleHeightFraction.ToString([System.Globalization.CultureInfo]::InvariantCulture)
)

& uv @pipelineArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "Pipeline failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "Vertical video processing completed successfully!" -ForegroundColor Green
