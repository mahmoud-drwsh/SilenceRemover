<# 
.SYNOPSIS
    Create links in a YT folder for short videos.

.DESCRIPTION
    Scans the current working directory for video files shorter than a duration
    threshold (default 179.5 seconds) and creates links to each match
    under ./YT while preserving relative folder structure.

    Designed for Windows with PowerShell and also works cross-platform where
    PowerShell can create links.

.PARAMETER Root
    Root directory to scan. Defaults to the current working directory.

.PARAMETER Destination
    Output folder for generated symlinks. Defaults to "YT" inside Root.

.PARAMETER MaxDurationSeconds
    Maximum duration threshold (seconds). Files with duration strictly less than this
    value are linked.

.PARAMETER LinkType
    Link strategy. HardLink saves space without admin requirements on NTFS and is
    recommended on Windows. SymbolicLink preserves behavior when you need it.

.PARAMETER FallbackToSymbolic
    If set, hard-link failures (for example cross-volume) will fall back to symbolic links.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Low')]
param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$Root = (Get-Location).Path,

    [Parameter(Mandatory = $false, Position = 1)]
    [string]$Destination = "YT",

    [Parameter(Mandatory = $false, Position = 2)]
    [double]$MaxDurationSeconds = 179.5,

    [Parameter(Mandatory = $false)]
    [ValidateSet('HardLink', 'SymbolicLink')]
    [string]$LinkType = 'HardLink',

    [Parameter(Mandatory = $false)]
    [switch]$FallbackToSymbolic,

    [Parameter(Mandatory = $false)]
    [string[]]$Extensions = @(
        '.mp4',
        '.m4v',
        '.mov',
        '.mkv',
        '.webm',
        '.avi',
        '.flv',
        '.wmv',
        '.mpeg',
        '.mpg',
        '.ts',
        '.m2ts',
        '.ogv'
    )
)

$rootPath = (Resolve-Path -LiteralPath $Root).Path
$destinationPath = [System.IO.Path]::GetFullPath((Join-Path $rootPath $Destination))
$ffprobePath = (Get-Command ffprobe -ErrorAction SilentlyContinue)?.Source

if (-not $ffprobePath) {
    throw "ffprobe was not found in PATH. Install FFmpeg/ffprobe and retry."
}

$normalizedExtensions = $Extensions | ForEach-Object {
    $ext = $_.Trim()
    if ([string]::IsNullOrWhiteSpace($ext)) { return $null }
    if ($ext.StartsWith('.')) { $ext.ToLowerInvariant() } else { ".${ext.ToLowerInvariant()}" }
}

$comparison = if ($IsWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
$destPrefix = $destinationPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)

if (-not (Test-Path -LiteralPath $destinationPath)) {
    New-Item -ItemType Directory -Path $destinationPath | Out-Null
    Write-Verbose "Created destination: $destinationPath"
}

function Get-VideoDurationSeconds {
    param([string]$Path)

    $output = & $ffprobePath -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -- "$Path" 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
        Write-Verbose "ffprobe failed for $Path"
        return $null
    }

    $durationText = $output.Trim()
    $duration = 0.0
    if (-not [double]::TryParse($durationText, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$duration)) {
        Write-Verbose "Could not parse duration '$durationText' for $Path"
        return $null
    }

    return $duration
}

function New-VideoSymlink {
    param(
        [string]$Source,
        [string]$LinkPath,
        [string]$RequestedLinkType,
        [bool]$UseFallback
    )

    if (Test-Path -LiteralPath $LinkPath) {
        Write-Host "[Skip] $LinkPath already exists"
        return $false
    }

    $linkDirectory = Split-Path -Parent $LinkPath
    if (-not (Test-Path -LiteralPath $linkDirectory)) {
        New-Item -ItemType Directory -Path $linkDirectory -Force | Out-Null
    }

    if ($PSCmdlet.ShouldProcess($LinkPath, "Create $RequestedLinkType link")) {
        try {
            New-Item -ItemType $RequestedLinkType -Path $LinkPath -Target $Source | Out-Null
            Write-Host "[Link] $RequestedLinkType $LinkPath -> $Source"
            return $true
        } catch {
            Write-Warning "Failed to create ${RequestedLinkType}: $LinkPath -> $Source. $($_.Exception.Message)"

            if ($RequestedLinkType -eq 'HardLink' -and $UseFallback) {
                try {
                    New-Item -ItemType SymbolicLink -Path $LinkPath -Target $Source | Out-Null
                    Write-Host "[Link] SymbolicLink (fallback) $LinkPath -> $Source"
                    return $true
                } catch {
                    Write-Warning "Fallback symbolic link failed: $LinkPath -> $Source. $($_.Exception.Message)"
                    return $false
                }
            }

            return $false
        }
    }

    return $false
}

$videoFiles = Get-ChildItem -LiteralPath $rootPath -File -Recurse | Where-Object {
    $ext = $_.Extension.ToLowerInvariant()
    $normalizedExtensions -contains $ext
} | Where-Object {
    $full = [System.IO.Path]::GetFullPath($_.FullName)
    -not $full.StartsWith($destPrefix, $comparison)
}

$total = 0
$linked = 0
foreach ($video in $videoFiles) {
    $total++
    $duration = Get-VideoDurationSeconds -Path $video.FullName
    if ($null -eq $duration) {
        Write-Verbose "Skipping unprocessable file: $($video.FullName)"
        continue
    }

    if ($duration -ge $MaxDurationSeconds) {
        Write-Verbose "Skipping (duration $duration): $($video.FullName)"
        continue
    }

    $relativePath = [System.IO.Path]::GetRelativePath($rootPath, $video.FullName)
    $targetPath = Join-Path -Path $destinationPath -ChildPath $relativePath
    if (New-VideoSymlink -Source $video.FullName -LinkPath $targetPath -RequestedLinkType $LinkType -UseFallback $FallbackToSymbolic.IsPresent) {
        $linked++
    }
}

Write-Host "Scanned $total videos. Linked $linked files to: $destinationPath"
