# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Extracts and transcribes the first 5 minutes of audio using OpenRouter (Gemini 2.0 Flash Lite)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **HEVC Encoding**: Uses libx265 HEVC encoder with CRF 23 for consistent quality. All encoding and decoding is software-based.

## Requirements

- **Python**: 3.11 or higher
- **FFmpeg & FFprobe**: Must be available on your system PATH
- **OpenRouter API Key**: Required for transcription and title generation (get one at [openrouter.ai](https://openrouter.ai))
- **Dependencies**: Managed via `pyproject.toml` (installed automatically)

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

All environment variables are centrally defined in `src/env_config.py` (the single source of truth). Configuration is validated at startup with clear error messages.

Create a `.env` file in the project root (or export environment variables) to configure the tool. See `.env.example` for all available variables.

**Minimum required configuration:**
```env
OPENROUTER_API_KEY=your_api_key_here
```

All other variables are optional and have sensible defaults. See `.env.example` for the complete list with descriptions.

### Parameter Tuning

- **NOISE_THRESHOLD**: Lower values (e.g., -40dB) detect quieter silences; higher values (e.g., -20dB) are more strict. Must be negative.
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
- `--debug`: Enable detailed debug output for silence detection and trimming operations

### Examples

Process videos with target length optimization:

```bash
python main.py ~/Videos/lectures --target-length 600
```

Process with debug output:

```bash
python main.py ~/Videos/lectures --debug
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

- **Transcription**: Extracts and transcribes audio using OpenRouter API (Gemini 2.0 Flash Lite model - cheapest audio-capable)
- Optimized for Arabic verbatim transcription
- **Title Generation**: Generates YouTube-style title from transcript using GPT-OSS 120B model
- Handles educational content formats (book names, lesson numbers)
- **Two-step process**: Separate API calls for transcription and title generation (better quality and control)
- Transcript and title are stored in `output/data.json` (single source of truth; no separate .txt files)

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

The tool includes built-in rate limiting and smart model selection:

- **Transcription**: Uses cheapest audio-capable model (`google/gemini-2.0-flash-lite-001`)
- **Title Generation**: 
  - Tries free OpenAI models first (`openai/gpt-oss-20b:free`, then `openai/gpt-oss-120b:free`)
  - Automatically falls back to paid model (`openai/gpt-oss-20b`) if free models hit rate limits
  - Cost: FREE in most cases, or ~$0.00000012 per title if fallback is needed
- Exponential backoff retry logic for rate limit errors (automatic retry with increasing delays)
- Sequential processing to respect API quotas

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
