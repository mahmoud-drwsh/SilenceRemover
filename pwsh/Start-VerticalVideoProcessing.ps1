param(
    [double]$TitleYFraction = 0.166667,      # 1/6 default - title position from top
    [double]$TitleHeightFraction = 0.166667  # 1/6 default - banner height
)

Set-Location C:\Users\user\scripts\SilenceRemover
uv run python main.py C:\Users\user\Videos\vertical\raw\ `
    --target-length 179.25 `
    --noise-threshold -40 `
    --enable-title-overlay `
    --enable-logo-overlay `
    --title-y-fraction $TitleYFraction `
    --title-height-fraction $TitleHeightFraction