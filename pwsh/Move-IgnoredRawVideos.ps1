param(
    [string]$VideosRoot = (Join-Path $HOME "Videos"),
    [double]$ShortDurationSeconds = 10.0,
    [double]$SilenceThresholdDb = -50.0,
    [double]$SilenceMinDurationSeconds = 0.1,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$videoExtensions = @(
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts"
)

$InvariantCulture = [System.Globalization.CultureInfo]::InvariantCulture

function Test-RequiredTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool '$Name' was not found on PATH."
    }
}

function Test-FileLocked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::None
        )
        $stream.Dispose()
        return $false
    } catch [System.UnauthorizedAccessException] {
        return $true
    } catch [System.IO.IOException] {
        return $true
    }
}

function Get-MediaDurationSeconds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $output = & ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -- $Path 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $raw = ($output | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }

    $duration = 0.0
    if (-not [double]::TryParse($raw, [System.Globalization.NumberStyles]::Float, $InvariantCulture, [ref]$duration)) {
        return $null
    }

    return $duration
}

function Test-HasAudioStream {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $output = & ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 -- $Path 2>$null
    return $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($output | Out-String).Trim())
}

function Test-FullySilentVideo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [double]$DurationSeconds
    )

    if ($DurationSeconds -le 0) {
        return $true
    }

    if (-not (Test-HasAudioStream -Path $Path)) {
        return $true
    }

    $silenceThresholdText = $SilenceThresholdDb.ToString($InvariantCulture)
    $silenceMinDurationText = $SilenceMinDurationSeconds.ToString($InvariantCulture)
    $filter = "silencedetect=n=${silenceThresholdText}dB:d=${silenceMinDurationText}"
    $ffmpegOutput = (& ffmpeg -hide_banner -nostats -v info -i $Path -map 0:a:0 -af $filter -f null - 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $startMatches = [regex]::Matches($ffmpegOutput, "silence_start:\s*(?<value>-?\d+(?:\.\d+)?)")
    $endMatches = [regex]::Matches($ffmpegOutput, "silence_end:\s*(?<value>-?\d+(?:\.\d+)?)")
    if ($startMatches.Count -eq 0 -or $endMatches.Count -eq 0) {
        return $false
    }

    $firstStart = 0.0
    $lastEnd = 0.0
    if (
        (-not [double]::TryParse($startMatches[0].Groups["value"].Value, [System.Globalization.NumberStyles]::Float, $InvariantCulture, [ref]$firstStart)) -or
        (-not [double]::TryParse($endMatches[$endMatches.Count - 1].Groups["value"].Value, [System.Globalization.NumberStyles]::Float, $InvariantCulture, [ref]$lastEnd))
    ) {
        return $false
    }

    $tolerance = [Math]::Max(0.15, [Math]::Min(0.5, $DurationSeconds * 0.01))
    return $firstStart -le $tolerance -and ($DurationSeconds - $lastEnd) -le $tolerance
}

function Get-UniqueIgnoredDestination {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File,
        [Parameter(Mandatory = $true)]
        [string]$IgnoredDir
    )

    $destination = Join-Path $IgnoredDir $File.Name
    if (-not (Test-Path -LiteralPath $destination)) {
        return $destination
    }

    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($File.Name)
    $extension = [System.IO.Path]::GetExtension($File.Name)
    for ($index = 1; $index -lt 1000; $index++) {
        $candidate = Join-Path $IgnoredDir ("{0}__ignored_{1}{2}" -f $baseName, $index, $extension)
        if (-not (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw "Could not find a unique ignored destination for '$($File.FullName)'."
}

function Move-ToIgnored {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File,
        [Parameter(Mandatory = $true)]
        [string]$IgnoredDir,
        [Parameter(Mandatory = $true)]
        [string]$Reason,
        [switch]$DryRunMove
    )

    if ($DryRunMove) {
        $destination = Join-Path $IgnoredDir $File.Name
        Write-Host ("  [dry-run] move '{0}' -> '{1}' ({2})" -f $File.Name, $destination, $Reason) -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path -LiteralPath $IgnoredDir)) {
        New-Item -ItemType Directory -Path $IgnoredDir -Force | Out-Null
    }

    $destination = Get-UniqueIgnoredDestination -File $File -IgnoredDir $IgnoredDir
    Move-Item -LiteralPath $File.FullName -Destination $destination
    Write-Host ("  moved '{0}' -> '{1}' ({2})" -f $File.Name, $destination, $Reason) -ForegroundColor Yellow
}

function Get-CompletedMarkerPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawPath,
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    $rootDir = Split-Path $RawPath -Parent
    return Join-Path $rootDir ("output\temp\completed\{0}.txt" -f $File.BaseName)
}

function Invoke-RawPreflightScan {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$RawPath
    )

    Write-Host "`n=== $Label raw preflight ===" -ForegroundColor Cyan
    if (-not (Test-Path -LiteralPath $RawPath)) {
        Write-Host "  raw directory not found: $RawPath" -ForegroundColor DarkGray
        return [pscustomobject]@{
            Label = $Label
            Scanned = 0
            Locked = 0
            CompletedSkipped = 0
            Moved = 0
        }
    }

    $ignoredDir = Join-Path $RawPath "ignored"
    $videoFiles = Get-ChildItem -LiteralPath $RawPath -File |
        Where-Object { $videoExtensions -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object Name

    if ($videoFiles.Count -eq 0) {
        Write-Host "  no supported video files found" -ForegroundColor DarkGray
        return [pscustomobject]@{
            Label = $Label
            Scanned = 0
            Locked = 0
            CompletedSkipped = 0
            Moved = 0
        }
    }

    $lockedCount = 0
    $movedCount = 0
    $completedSkipCount = 0

    foreach ($file in $videoFiles) {
        if (Test-FileLocked -Path $file.FullName) {
            $lockedCount++
            Write-Host ("  skipping locked file: {0}" -f $file.Name) -ForegroundColor DarkGray
            continue
        }

        $completedMarkerPath = Get-CompletedMarkerPath -RawPath $RawPath -File $file
        if (Test-Path -LiteralPath $completedMarkerPath) {
            $completedSkipCount++
            Write-Host ("  skip preflight: {0} (completed marker exists)" -f $file.Name) -ForegroundColor DarkGray
            continue
        }

        if ($file.Length -le 0) {
            Move-ToIgnored -File $file -IgnoredDir $ignoredDir -Reason "empty file" -DryRunMove:$DryRun
            $movedCount++
            continue
        }

        $duration = Get-MediaDurationSeconds -Path $file.FullName
        if ($null -eq $duration -or $duration -le 0) {
            Move-ToIgnored -File $file -IgnoredDir $ignoredDir -Reason "missing or invalid duration" -DryRunMove:$DryRun
            $movedCount++
            continue
        }

        if ($duration -lt $ShortDurationSeconds) {
            Move-ToIgnored -File $file -IgnoredDir $ignoredDir -Reason ("too short ({0:N2}s < {1:N2}s)" -f $duration, $ShortDurationSeconds) -DryRunMove:$DryRun
            $movedCount++
            continue
        }

        if (Test-FullySilentVideo -Path $file.FullName -DurationSeconds $duration) {
            Move-ToIgnored -File $file -IgnoredDir $ignoredDir -Reason ("fully silent ({0:N2}s)" -f $duration) -DryRunMove:$DryRun
            $movedCount++
            continue
        }

        Write-Host ("  keeping '{0}' ({1:N2}s)" -f $file.Name, $duration) -ForegroundColor Green
    }

    return [pscustomobject]@{
        Label = $Label
        Scanned = $videoFiles.Count
        Locked = $lockedCount
        CompletedSkipped = $completedSkipCount
        Moved = $movedCount
    }
}

Test-RequiredTool -Name "ffmpeg"
Test-RequiredTool -Name "ffprobe"

$horizontalRaw = Join-Path $VideosRoot "raw"
$verticalRaw = Join-Path (Join-Path $VideosRoot "Vertical") "raw"

$summaries = @(
    Invoke-RawPreflightScan -Label "Horizontal" -RawPath $horizontalRaw
    Invoke-RawPreflightScan -Label "Vertical" -RawPath $verticalRaw
)

Write-Host "`n=== Raw preflight summary ===" -ForegroundColor Cyan
foreach ($summary in $summaries) {
    Write-Host (
        "  {0}: scanned {1}, locked {2}, completed-skip {3}, moved {4}" -f
        $summary.Label,
        $summary.Scanned,
        $summary.Locked,
        $summary.CompletedSkipped,
        $summary.Moved
    ) -ForegroundColor White
}
