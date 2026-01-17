# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Extracts and transcribes the first 5 minutes of audio using OpenRouter (Gemini 2.0 Flash Lite)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **Hardware Acceleration**: Automatically uses available hardware encoders (QSV, VideoToolbox, AMF) with fallback to software encoding

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

Create a `.env` file in the project root (or export environment variables) to configure the tool:

```env
# Silence detection parameters
NOISE_THRESHOLD=-30.0  # dB threshold for silence detection
MIN_DURATION=0.5       # Minimum silence duration (seconds)
PAD=0.5                # Padding retained around silences (seconds)

# OpenRouter API
OPENROUTER_API_KEY=your_api_key_here
```

### Parameter Tuning

- **NOISE_THRESHOLD**: Lower values (e.g., -40dB) detect quieter silences; higher values (e.g., -20dB) are more strict
- **MIN_DURATION**: Minimum length of silence to be detected (prevents removing brief pauses)
- **PAD**: Amount of audio/video retained around detected silences (helps preserve natural transitions)

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
- **Title Generation**: Generates YouTube-style title from transcript using dedicated text-only models
- Handles educational content formats (book names, lesson numbers)
- **Two-step process**: Separate API calls for transcription and title generation (better quality and control)
- **Smart fallback**: Title generation tries free OpenAI models first, automatically falls back to paid model if free models hit rate limits
- Stores transcript (`.txt`) and title (`.title.txt`) in `temp/` directory

### 4. File Renaming

- Reads generated title from `temp/` directory
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
  ├── generated-title-1.mp4
  └── generated-title-2.mkv

temp/                      # Sibling to input-directory
  ├── video1.m4a          # Extracted audio
  ├── video1.txt          # Transcript
  ├── video1.title.txt    # Generated title
  ├── video2.m4a
  ├── video2.txt
  ├── video2.title.txt
  └── _processed_vids.json # Processing tracking database
```

## Process Tracking

The tool maintains a tracking database (`temp/_processed_vids.json`) to avoid reprocessing videos:

- **Automatic Skip**: Videos already in the database are skipped
- **Metadata Tracking**: Stores processing timestamp for each video
- **Manual Reset**: Delete `_processed_vids.json` to reprocess all videos

## Supported Formats

**Video Extensions**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.3gp`, `.ogv`, `.ts`, `.m2ts`

**Hardware Encoders** (auto-detected):
- Intel Quick Sync: `hevc_qsv`, `h264_qsv`
- Apple VideoToolbox: `h264_videotoolbox`
- AMD AMF: `h264_amf`
- Fallback: `libx264` (software)

## API Rate Limiting & Model Selection

The tool includes built-in rate limiting and smart model selection:

- **Transcription**: Uses cheapest audio-capable model (`google/gemini-2.0-flash-lite-001`)
- **Title Generation**: 
  - Tries free OpenAI models first (`openai/gpt-oss-20b:free`, then `openai/gpt-oss-120b:free`)
  - Automatically falls back to paid model (`openai/gpt-oss-20b`) if free models hit rate limits
  - Cost: FREE in most cases, or ~$0.00000012 per title if fallback is needed
- Automatic cooldown between API requests (2 seconds default)
- Exponential backoff retry logic for rate limit errors
- Sequential processing to respect API quotas

## Error Handling

- **Missing Tools**: Validates FFmpeg/FFprobe availability before processing
- **API Errors**: Automatic retry with exponential backoff
- **Encoding Failures**: Falls back to software encoder if hardware encoder fails
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

### Hardware Encoding Fails

The tool automatically falls back to software encoding (`libx264`) if hardware encoding fails. Check debug output for encoder selection:

```bash
python main.py /path/to/videos --debug
```

### Output Copy Fails on Windows

- Windows can temporarily lock freshly exported videos (e.g., antivirus scan or preview in Explorer), which results in `PermissionError` during copying.
- The tool now retries the copy operation with automatic backoff until the file is released.
- To manually verify, open a processed video in a player to keep it locked, rerun the script, and observe the retry log messages. Once the lock is released, the copy should complete successfully.

## License

[Add your license information here]

## Contributing

[Add contribution guidelines if applicable]
