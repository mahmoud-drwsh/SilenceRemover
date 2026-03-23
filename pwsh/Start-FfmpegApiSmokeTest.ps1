$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
uv run python tests/ffmpeg_api_smoke.py

