# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Builds a silence-removed snippet (capped at `SNIPPET_MAX_DURATION_SEC`, 180s / 3 minutes by default), encodes it as Ogg/Opus, and transcribes via OpenRouter (default model: `google/gemini-3.1-flash-lite-preview`)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **Video encoding**: Uses a centralized resolver that currently tries HEVC Intel Quick Sync (`hevc_qsv`) first, then Apple VideoToolbox (`hevc_videotoolbox`). The resolver design is intentionally extensible for future hardware encoders, and failures are reported directly without codec fallback.
- **FFmpeg Centralization**: Consolidates command building, execution, probing, and filter graph generation under the new `src/ffmpeg` package.

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

All configuration is defined in `src/core/config.py` (the single source of truth) plus a small set of CLI flags. Environment variables are only used for secrets.

Keep only **secrets** in `.env` (your OpenRouter API key). Copy `.env.example` to `.env` and set:

```env
OPENROUTER_API_KEY=your_api_key_here
```

All other options (models, silence parameters, timeouts, etc.) are controlled via CLI flags or constants in `src/core/config.py` and `src/core/constants.py`.

## Usage

### Basic Usage

Process all videos in a directory:

```bash
python main.py /path/to/video/directory
```

### Options

- `--target-length FLOAT`: Optimize padding to achieve a target video length (in seconds).
- `--noise-threshold FLOAT`: Override silence detection threshold in dB (e.g. `-55`). Defaults are `TARGET_NOISE_THRESHOLD_DB` (`-55.0`) when `--target-length` is set, otherwise `NON_TARGET_NOISE_THRESHOLD_DB` (`-50.0`).
- `--min-duration FLOAT`: Override minimum silence duration in seconds (applies in both modes). Defaults are `TARGET_MIN_DURATION_SEC` (`0.01`) with `--target-length` and `NON_TARGET_MIN_DURATION_SEC` (`1.0`) otherwise.
- `--llm-only`: Run **phases 1–2 only** (silence-removed snippet, transcription, title). Skips hardware encoder probing and **Phase 3** (no final MP4). After processing, prints each video’s transcript and title to the console. Also maintains an append-only log at `output/temp/titles.txt`: after Phase 1 finishes for all videos, each run appends a `======` / timestamp / `======` header (with blank lines before it if the file already has content), then Phase 2 appends one tab-separated line per video (`stem<TAB>title`) as soon as that video’s title step completes (including when the title phase is skipped as already done).
- `--title-font`: Google Font family name used to render the title overlay. The font is auto-downloaded from Google Fonts on first use and cached under `output/temp/fonts/`.

### Suggested Arabic-friendly Google Fonts
- `Noto Naskh Arabic`
- `Noto Kufi Arabic`
- `Cairo`
- `Tajawal`
- `Amiri`
- `IBM Plex Sans Arabic`
- `Mada`

The first run for each font downloads the family from Google Fonts into `output/temp/fonts/` and reuses that file on subsequent runs.

**Video-only files (no audio stream):** Some exports are silent (video track only). The pipeline detects missing audio with ffprobe, skips `silencedetect` (which would otherwise fail on `-map 0:a:0`), generates a **silent** transcription snippet from the video duration, and muxes **silent stereo** from `anullsrc` during the final trim/encode so Phase 3 still produces a valid MP4 with a title overlay. Transcripts will be empty or minimal for those inputs.

Trimming precision controls (advanced):

- `src/core/constants.py`: `TRIM_DECIMAL_PLACES` controls timestamp precision used when calculating and applying segment boundaries (default `6`).
- `src/core/constants.py`: `PAD_INCREMENT_SEC` controls target-length padding search granularity (default `0.001`).
- `src/core/constants.py`: `TRIM_TIMESTAMP_EPSILON_SEC` controls floating-point under-target tolerance in length checks.

### Examples

Process videos with target length optimization:

```bash
python main.py ~/Videos/lectures --target-length 600
```

Customize title typography with a specific Google Font:

```bash
python main.py ~/Videos/lectures --title-font "Cairo"
```

## FFmpeg Command Architecture

FFmpeg responsibilities are now organized in the `src/ffmpeg` package:

- `core.py`: shared command builders and debug formatting for ffmpeg/ffprobe.
- `runner.py`: standardized run and streaming-progress execution helpers.
- `probing.py`: duration/bitrate probes and encoder capability checks.
- `detection.py`: silencedetect command construction and result parsing.
- `filter_graph.py`: reusable audio/video concat graph builders.
- `transcode.py`: extraction and encode command builders for transcription and trimming.

## How It Works

The tool processes videos sequentially through four main stages:

### 1. Silence Detection & Trimming

- Analyzes audio track using FFmpeg's `silencedetect` filter
- Identifies silence segments based on configured threshold and duration
- Removes silence while preserving padding around segments
- For phase 1 transcription snippets, a fixed single sweep is used: `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`), and the same shared edge normalization helper as final trim.
- Leading and trailing edge silences are re-scanned at `EDGE_RESCAN_THRESHOLD_DB` (`-55dB`) for both target and non-target final trim runs, then only the edge windows are replaced and reduced to a `EDGE_SILENCE_KEEP_SEC` (200ms) buffer before pad calculations.
- Outputs trimmed video to `temp/` directory (sibling to input directory)

**Target Length Mode**: When `--target-length` is specified, the tool automatically calculates optimal padding to get as close as possible to the target duration.

### 2. Audio Extraction

- Extracts up to 3 minutes (`SNIPPET_MAX_DURATION_SEC` = 180s) of silence-removed snippet audio for transcription using the same edge policy as final trim.
- Saves as `.ogg` (Opus) under `temp/snippet/` (see `get_snippet_path` / `AUDIO_FILE_EXT`)
- Phase-1 snippet extraction ignores `--noise-threshold`/`--min-duration` overrides and always uses `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`) via snippet defaults.
- Reuses existing audio files if already extracted

### 3. Transcription & Title Generation

- **Transcription** (`src/llm/transcription.py`): Extracts and transcribes audio using OpenRouter API (default model: `google/gemini-3.1-flash-lite-preview`). Optimized for Arabic verbatim transcription.
- **Title** (`src/llm/title.py`): Generates a YouTube-style title from transcript text.
- Both use a shared OpenRouter client (`src/llm/client.py`). Pipeline orchestration is in `src/app/pipeline.py`.
- **Two-step process**: Separate API calls for transcription and title generation (better quality and control). Transcript and title are stored in `temp/transcript/{basename}.txt` and `temp/title/{basename}.txt`.
- **Title extraction constraints**:
  - Output is exactly one Arabic title line (no commentary).
  - The title must be a verbatim contiguous span from the transcript.
  - The title is extracted from the opening complete-sentence portion at the start of the transcript (title-intro area), not from later answer/explanatory body text.
  - The model produces a small pool of candidate titles in **one** generation call (JSON array of distinct titles). A **second** call scores every candidate in one shot (`verbatim_score` and `correctness_score`, each 0–10); the implementation picks the highest **combined** score (sum). Ties break deterministically (earliest transcript substring match, then length near a practical band, then candidate order).
  - The final title is returned after that scoring step (no further LLM calls).

### 4. File Renaming

### 5. Title Overlay Rendering (Phase 3)

- The title text from `temp/title/{basename}.txt` is loaded right before output encoding.
- `ffprobe` reads the source **video width and height**. A **banner-sized** RGBA PNG (`video_width` × `banner_height`, where `banner_height = 20%` of frame height) is written to `temp/title_overlays/{basename}.png`. FFmpeg composites it at `x=0`, `y=20%` of frame height (`overlay=0:{y}`), so it occupies the band from **frame y = 1/5** to **2/5** (same geometry as the old drawbox region).
- The PNG is a semi-transparent black strip (`TITLE_BANNER_BG_ALPHA`, default 0.5) with **white** title text rendered in Pillow using the selected `--title-font` (Google Font, cached under `temp/fonts/`).
- **Layout algorithm** (largest font that fits, optional two-line word splits, bbox-based metrics, vertical stacking): see **`ALGO.md` → “Title overlay PNG”**.
- **Arabic / RTL titles**: Pillow draws in visual order only; text is shaped with `arabic-reshaper` and reordered with `python-bidi` (`get_display`) before measuring and drawing. Mixed Arabic + Latin/numbers follow Unicode bidirectional rules.
- FFmpeg applies this PNG in the trim/concat filter graph; no `drawtext` dependency for the final overlay.

- Reads generated title from `temp/title/{basename}.txt`
- Sanitizes filename (removes invalid characters)
- Handles duplicate names by appending `_N` suffix
- Writes trimmed video from `output/temp/` to `output/` directory with the new title-based filename

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

temp/                      # Sibling to input-directory (intermediate audio/snippets only)
  ├── snippet/             # Silence-removed snippets for transcription
  ├── transcript/          # Transcript text files
  ├── title/               # Title text files
  ├── completed/           # Completion markers
  ├── scripts/             # Temporary ffmpeg filter_complex scripts (cleaned up automatically)
  └── ...
```

## Process Tracking

The tool maintains state in files inside `temp/` to avoid reprocessing videos:

- **Per-video markers**: `transcript/{basename}.txt`, `title/{basename}.txt`, and `completed/{basename}.txt`
- **Automatic Skip**: Phase 1 is skipped if transcript exists; Phase 2 is skipped if title exists; Phase 3 is skipped when completed marker exists
- **Manual Reset**: Delete corresponding files under `temp/transcript`, `temp/title`, and `temp/completed` to reprocess specific videos.

## Supported Formats

**Video Extensions**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.3gp`, `.ogv`, `.ts`, `.m2ts`

## API Rate Limiting & Model Selection

The tool includes built-in retry logic for rate limit errors (exponential backoff) and processes videos sequentially to respect API quotas.

- **Defaults**: Both transcription and title generation default to `google/gemini-3.1-flash-lite-preview` (see the helper modules under `src/llm/transcription.py` and `src/llm/title.py`).

## Domain Package Layout

The project is organized into six packages:

- `src/core`: shared constants, config loading, path utilities, and CLI utilities.
- `src/media`: silence detection and trimming algorithms.
- `src/llm`: OpenRouter client, prompt templates, transcription, and title flows.
- `src/app`: high-level pipeline orchestration (`run` entrypoint).
- `src/ffmpeg`: centralized FFmpeg command construction, probing, execution, and filter-graph helpers.
- `src/startup`: startup bootstrap and runtime context assembly.

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

Note: This project’s shared FFmpeg command builder (`src/ffmpeg/core.py:add_filter_complex_script`) uses the non-deprecated filter graph script option `-/filter_complex`, so you should no longer see the `-filter_complex_script is deprecated` warning in normal runs.

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
