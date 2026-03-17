# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Extracts and transcribes the first 5 minutes of audio using OpenRouter (default model: `google/gemini-2.5-flash-lite:nitro`)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **H.264 Encoding**: Uses Intel Quick Sync (h264_qsv) with high-quality options (preset slower, look-ahead, RDO, etc.); falls back to libx264 if QSV is unavailable. Quality controlled by `VIDEO_CRF` (default 23).

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

All configuration (environment variables and static constants) is defined in `src/config.py` (the single source of truth). Configuration is validated at startup with clear error messages.

Keep only **secrets** in `.env` (e.g. your OpenRouter API key). Copy `.env.example` to `.env` and set:

```env
OPENROUTER_API_KEY=your_api_key_here
```

All other options (models, silence params, timeouts, etc.) have defaults in `src/config.py` and can be overridden via environment variables if needed.

### Parameter Tuning

- **NOISE_THRESHOLD**: Default is -50dB. Lower values (e.g., -55dB) detect quieter silences; higher values (e.g., -30dB) are more strict. Must be negative.
- **MIN_DURATION**: Minimum length of silence to be detected (prevents removing brief pauses). Must be positive.
- **PAD**: Amount of audio/video retained around detected silences (helps preserve natural transitions). Must be non-negative.

**Note:** Invalid configuration values will cause the tool to fail at startup with clear error messages indicating what needs to be fixed.

## Usage

### Basic Usage

Process all videos in a directory:

```bash
python main.py /path/to/video/directory
```

### Options

- `--target-length FLOAT`: Optimize padding to achieve a target video length (in seconds)
- `--noise-threshold FLOAT`: Override silence detection threshold in dB (e.g. `-55`). With `--target-length`, defaults to SIMPLE_DB if not set.
- `--min-duration FLOAT`: Override minimum silence duration in seconds (e.g. `0.5`). With `--target-length`, defaults to SIMPLE_MIN_DURATION if not set.

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

- **Transcription** (`src/transcribe.py`): Extracts and transcribes audio using OpenRouter API (default model: `google/gemini-2.5-flash-lite:nitro`; override via `OPENROUTER_DEFAULT_MODEL`). Optimized for Arabic verbatim transcription.
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

- **Defaults**: Both transcription and title generation default to `google/gemini-2.5-flash-lite:nitro` (see `src/config.py`).
- **Overrides**: You can override models via `OPENROUTER_DEFAULT_MODEL` and `OPENROUTER_TITLE_MODEL` environment variables.

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
