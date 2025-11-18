# Cleanup script for processed video files
# Moves files from raw to archive and deletes temp and output directories

$basePath = "C:\Users\user\Videos"

# Function to cleanup a specific directory
function Cleanup-Directory {
    param(
        [string]$RawPath,
        [string]$ArchivePath,
        [string]$TempPath,
        [string]$OutputPath,
        [string]$DirectoryName
    )
    
    Write-Host "`n=== Cleaning up $DirectoryName ===" -ForegroundColor Cyan
    
    # Move files from raw to archive
    if (Test-Path $RawPath) {
        $files = Get-ChildItem -Path $RawPath -File
        if ($files.Count -gt 0) {
            # Create archive directory if it doesn't exist
            if (-not (Test-Path $ArchivePath)) {
                New-Item -ItemType Directory -Path $ArchivePath -Force | Out-Null
                Write-Host "Created archive directory: $ArchivePath" -ForegroundColor Yellow
            }
            
            Write-Host "Moving $($files.Count) file(s) from raw to archive..." -ForegroundColor Yellow
            foreach ($file in $files) {
                $destPath = Join-Path $ArchivePath $file.Name
                Move-Item -Path $file.FullName -Destination $destPath -Force
                Write-Host "  Moved: $($file.Name)" -ForegroundColor Gray
            }
            Write-Host "✓ Files moved to archive" -ForegroundColor Green
        } else {
            Write-Host "No files found in raw directory" -ForegroundColor Gray
        }
    } else {
        Write-Host "Raw directory does not exist: $RawPath" -ForegroundColor Gray
    }
    
    # Delete temp directory
    if (Test-Path $TempPath) {
        Write-Host "Deleting temp directory..." -ForegroundColor Yellow
        Remove-Item -Path $TempPath -Recurse -Force
        Write-Host "✓ Temp directory deleted" -ForegroundColor Green
    } else {
        Write-Host "Temp directory does not exist: $TempPath" -ForegroundColor Gray
    }
    
    # Delete output directory
    if (Test-Path $OutputPath) {
        Write-Host "Deleting output directory..." -ForegroundColor Yellow
        Remove-Item -Path $OutputPath -Recurse -Force
        Write-Host "✓ Output directory deleted" -ForegroundColor Green
    } else {
        Write-Host "Output directory does not exist: $OutputPath" -ForegroundColor Gray
    }
}

# Prompt user for selection
Write-Host "`n=== Cleanup Processed Files ===" -ForegroundColor Cyan
Write-Host "Select cleanup option:"
Write-Host "  1 - Clean up horizontal directory only"
Write-Host "  2 - Clean up vertical directory only"
Write-Host "  3 - Clean up all directories"
Write-Host ""

$selection = Read-Host "Enter selection (1-3)"

switch ($selection) {
    "1" {
        # Horizontal directory cleanup
        $rawPath = Join-Path $basePath "raw"
        $archivePath = Join-Path $basePath "archive"
        $tempPath = Join-Path $basePath "temp"
        $outputPath = Join-Path $basePath "output"
        
        Cleanup-Directory -RawPath $rawPath -ArchivePath $archivePath -TempPath $tempPath -OutputPath $outputPath -DirectoryName "Horizontal"
    }
    "2" {
        # Vertical directory cleanup
        $rawPath = Join-Path $basePath "vertical\raw"
        $archivePath = Join-Path $basePath "vertical\archive"
        $tempPath = Join-Path $basePath "vertical\temp"
        $outputPath = Join-Path $basePath "vertical\output"
        
        Cleanup-Directory -RawPath $rawPath -ArchivePath $archivePath -TempPath $tempPath -OutputPath $outputPath -DirectoryName "Vertical"
    }
    "3" {
        # Clean up both horizontal and vertical
        Write-Host "`nCleaning up ALL directories..." -ForegroundColor Cyan
        
        # Horizontal
        $rawPath = Join-Path $basePath "raw"
        $archivePath = Join-Path $basePath "archive"
        $tempPath = Join-Path $basePath "temp"
        $outputPath = Join-Path $basePath "output"
        
        Cleanup-Directory -RawPath $rawPath -ArchivePath $archivePath -TempPath $tempPath -OutputPath $outputPath -DirectoryName "Horizontal"
        
        # Vertical
        $rawPath = Join-Path $basePath "vertical\raw"
        $archivePath = Join-Path $basePath "vertical\archive"
        $tempPath = Join-Path $basePath "vertical\temp"
        $outputPath = Join-Path $basePath "vertical\output"
        
        Cleanup-Directory -RawPath $rawPath -ArchivePath $archivePath -TempPath $tempPath -OutputPath $outputPath -DirectoryName "Vertical"
    }
    default {
        Write-Host "Invalid selection. Please run the script again and select 1, 2, or 3." -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Cleanup Complete ===" -ForegroundColor Green

