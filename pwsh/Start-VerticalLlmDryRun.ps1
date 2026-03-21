# LLM-only / dry run: transcription + titles for vertical raw folder (no Phase 3 encode).
# Writes snippets/transcripts/titles under vertical/output/temp and appends titles.txt per run.
Set-Location C:\Users\user\scripts\SilenceRemover
uv run python main.py C:\Users\user\Videos\vertical\raw\ --llm-only
