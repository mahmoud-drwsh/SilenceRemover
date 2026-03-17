# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Extracts and transcribes the first 5 minutes of audio using OpenRouter (default model: `google/gemini-2.5-flash-lite:nitro`)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **H.264 Encoding**: Uses Intel Quick Sync (`hevc_qsv`) with high-quality options (slower preset, look-ahead, RDO-style bitrate controls, etc.). Encoding now uses a single `hevc_qsv` path; failures are reported directly without codec fallback.

## Requirements

- **Python**: 3.11 or higher
- **FFmpeg & FFprobe**: Must be available on your system PATH
- **OpenRouter API Key**: Required for transcription and title generation (get one at [openrouter.ai](https://openrouter.ai))
- **Dependencies**: Managed via `pyproject.toml` (installed automatically). Transcription and title generation use the official [OpenRouter Python SDK](https://openrouter.ai/docs/sdks/python).

## Installation

### Using pip

```bash
pip install -e .
```

### Using uv (recommended)

This project uses `uv` for dependency management. If you have `uv` installed:

```bash
uv sync
```

## Configuration

All configuration is defined in `src/config.py` (the single source of truth) plus a small set of CLI flags. Environment variables are only used for secrets.

Keep only **secrets** in `.env` (your OpenRouter API key). Copy `.env.example` to `.env` and set:

```env
OPENROUTER_API_KEY=your_api_key_here
```

All other options (models, silence parameters, timeouts, etc.) are controlled via CLI flags or constants in `src/config.py` and `src/constants.py`.

## Usage

### Basic Usage

Process all videos in a directory:

```bash
python main.py /path/to/video/directory
```

### Options

- `--target-length FLOAT`: Optimize padding to achieve a target video length (in seconds).
- `--noise-threshold FLOAT`: Override silence detection threshold in dB (e.g. `-55`). Without `--target-length`, defaults to a conservative value from `src/config.py`.
- `--min-duration FLOAT`: Override minimum silence duration in seconds (e.g. `0.5`). Without `--target-length`, defaults to a value from `src/config.py`.

Trimming precision controls (advanced):

- `src/constants.py`: `TRIM_DECIMAL_PLACES` controls timestamp precision used when calculating and applying segment boundaries (default `6`).
- `src/constants.py`: `PAD_INCREMENT_SEC` controls target-length padding search granularity (default `0.001`).
- `src/constants.py`: `TRIM_TIMESTAMP_EPSILON_SEC` controls floating-point under-target tolerance in length checks.

### Examples

Process videos with target length optimization:

```bash
python main.py ~/Videos/lectures --target-length 600
```

## How It Works

The tool processes videos sequentially through four main stages:

### 1. Silence Detection & Trimming

- Analyzes audio track using FFmpeg's `silencedetect` filter
- Identifies silence segments based on configured threshold and duration
- Removes silence while preserving padding around segments
- Outputs trimmed video to `temp/` directory (sibling to input directory)

**Target Length Mode**: When `--target-length` is specified, the tool automatically calculates optimal padding to get as close as possible to the target duration.

### 2. Audio Extraction

- Extracts first 5 minutes of audio from the trimmed video
- Saves as `.m4a` file in `temp/` directory
- Reuses existing audio files if already extracted

### 3. Transcription & Title Generation

- **Transcription** (`src/transcribe.py`): Extracts and transcribes audio using OpenRouter API (default model: `google/gemini-2.5-flash-lite:nitro`). Optimized for Arabic verbatim transcription.
- **Title** (`src/title.py`): Generates YouTube-style title from transcript. Handles educational content formats (book names, lesson numbers).
- Both use a shared OpenRouter client (`src/openrouter_client.py`). Phase 1 orchestration is in `src/phase1.py`.
- **Two-step process**: Separate API calls for transcription and title generation (better quality and control). Transcript and title are stored in `output/data.json` (single source of truth; no separate .txt files).

### 4. File Renaming

- Reads generated title from `output/data.json`
- Sanitizes filename (removes invalid characters)
- Handles duplicate names by appending `_N` suffix
- Copies trimmed video from `temp/` to `output/` directory with the new title-based filename

## Directory Structure

After processing, your directory structure will look like this:

```
input-directory/
  ├── video1.mp4
  ├── video2.mkv
  └── ...

output/                    # Sibling to input-directory
  ├── data.json           # Transcript, title, and completion state per video
  ├── generated-title-1.mp4
  └── generated-title-2.mkv

temp/                      # Sibling to input-directory (intermediate audio/snippets only)
  ├── video1_snippet.wav   # Silence-removed snippet for transcription
  ├── scripts/             # Temporary ffmpeg filter_complex scripts (cleaned up automatically)
  └── ...
```

## Process Tracking

The tool maintains state in `output/data.json` to avoid reprocessing videos:

- **Per-video keys**: `transcript`, `title`, and `completed` (Phase 1 vs Phase 2 done)
- **Automatic Skip**: Phase 1 is skipped if transcript and title already exist for that video; Phase 2 is skipped if `completed` is true
- **Manual Reset**: Edit or delete entries in `data.json` to reprocess specific videos (or delete the file to reprocess all)

## Supported Formats

**Video Extensions**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.3gp`, `.ogv`, `.ts`, `.m2ts`

## API Rate Limiting & Model Selection

The tool includes built-in retry logic for rate limit errors (exponential backoff) and processes videos sequentially to respect API quotas.

- **Defaults**: Both transcription and title generation default to `google/gemini-2.5-flash-lite:nitro` (see the OpenRouter helper modules under `src/transcription` and `src/titles`).

## Error Handling

- **Missing Tools**: Validates FFmpeg/FFprobe availability before processing
- **API Errors**: Automatic retry with exponential backoff
- **Encoding Failures**: FFmpeg encoding errors are reported directly (no fallback)
- **Invalid Videos**: Skips corrupted or unreadable files with error messages

## Troubleshooting

### FFmpeg not found

Ensure FFmpeg and FFprobe are installed and available on your PATH:

```bash
ffmpeg -version
ffprobe -version
```

Note: This project uses FFmpeg's non-deprecated filter graph script option `-/filter_complex`, so you should no longer see `-filter_complex_script is deprecated` warnings in normal runs.

### API Key Issues

Verify your OpenRouter API key is set correctly:

```bash
echo $OPENROUTER_API_KEY
```

Or check your `.env` file is loaded properly.

**Note**: OpenRouter requires a minimum balance of $0.50 to process audio files. Make sure your account has sufficient funds.

## License

[Add your license information here]

## Contributing

[Add contribution guidelines if applicable]
