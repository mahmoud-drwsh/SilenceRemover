# PowerShell one-liner to test hardware encoders
# Run this in PowerShell to test all encoders

$encoders = @(
    @("hevc_qsv", "Intel QSV HEVC"),
    @("hevc_amf", "AMD AMF HEVC"),
    @("hevc_nvenc", "NVIDIA NVENC HEVC"),
    @("h264_qsv", "Intel QSV H.264"),
    @("h264_amf", "AMD AMF H.264"),
    @("h264_nvenc", "NVIDIA NVENC H.264"),
    @("libx265", "Software HEVC"),
    @("libx264", "Software H.264")
)

Write-Host "Testing hardware encoders..." -ForegroundColor Cyan
Write-Host ("=" * 60)

foreach ($enc in $encoders) {
    $codec = $enc[0]
    $name = $enc[1]
    
    Write-Host -NoNewline "Testing $name ($codec)... "
    
    $proc = Start-Process -FilePath "ffmpeg" -ArgumentList @(
        "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
        "-frames:v", "2",
        "-c:v", $codec,
        "-pix_fmt", "yuv420p",
        "-f", "null", "-"
    ) -PassThru -WindowStyle Hidden -Wait
    
    if ($proc.ExitCode -eq 0) {
        Write-Host "[OK]" -ForegroundColor Green
    } else {
        Write-Host "[FAIL]" -ForegroundColor Red
    }
}

Write-Host ("=" * 60)
Write-Host "Done!" -ForegroundColor Cyan
