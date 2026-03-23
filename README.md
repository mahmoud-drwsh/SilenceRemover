# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Builds a silence-removed snippet (capped at `SNIPPET_MAX_DURATION_SEC`, 180s / 3 minutes by default), encodes it as Ogg/Opus, and transcribes via OpenRouter (default model: `google/gemini-3.1-flash-lite-preview`)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **Video encoding**: Final MP4 video is always encoded with **libx265** (software HEVC). Startup probes FFmpeg for a working `libx265` encoder; there is no hardware path and no codec fallback. Use a **full FFmpeg build that includes libx265** (often GPL-licensed); verify with `ffmpeg -hide_banner -encoders` and look for `libx265`.
- **FFmpeg Centralization**: Consolidates command building, execution, probing, and filter graph generation under the new `src/ffmpeg` package.

## Requirements

- **Python**: 3.11 or higher
- **FFmpeg & FFprobe**: Must be on your PATH; the build must include **encoder `libx265`** (many minimal or LGPL-only builds omit it—use a full/GNU build if startup fails with a libx265 message).
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

### Title editor only

Run the local FastAPI UI to edit titles (no transcription or encoding):

```bash
python main.py /path/to/video/directory --title-editor
```

Requires FFmpeg/ffprobe on PATH (same as the layout helper). Optional: set `TITLE_EDITOR_PORT` (default `8765`).

### Options

- `--target-length FLOAT`: Optimize padding to achieve a target video length (in seconds).
- `--noise-threshold FLOAT`: Override silence detection threshold in dB (e.g. `-55`). Defaults are `TARGET_NOISE_THRESHOLD_DB` (`-55.0`) when `--target-length` is set, otherwise `NON_TARGET_NOISE_THRESHOLD_DB` (`-50.0`).
- `--min-duration FLOAT`: Override minimum silence duration in seconds (applies in both modes). Defaults are `TARGET_MIN_DURATION_SEC` (`0.01`) with `--target-length` and `NON_TARGET_MIN_DURATION_SEC` (`1.0`) otherwise.
- `--title-font`: Google Font family name used to render the title overlay. The font is auto-downloaded from Google Fonts on first use and cached under `output/temp/fonts/`.
- `--quick-test`: Run all three phases, but cap only the final Phase 3 encode output to the first 5 seconds for a fast end-to-end smoke run.
- `--title-editor`: Start only the title editor web server for `input_dir`; ignores pipeline flags.

### Suggested Arabic-friendly Google Fonts
- `Noto Naskh Arabic`
- `Noto Kufi Arabic`
- `Cairo`
- `Tajawal`
- `Amiri`
- `IBM Plex Sans Arabic`
- `Mada`

The first run for each font downloads the family from Google Fonts into `output/temp/fonts/` and reuses that file on subsequent runs.

**Video-only files (no audio stream):** Some exports are silent (video track only). The pipeline detects missing audio with ffprobe, skips `silencedetect` (which would otherwise fail on `-map 0:a:0`), generates a **silent** transcription snippet from the video duration, and muxes **silent stereo** from `anullsrc` during the final trim/encode when a full encode runs. **Transcription** still calls OpenRouter on that snippet; if the model returns **empty or whitespace-only** text, **no** `output/temp/transcript/{basename}.txt` is written, Phase 1 fails for that video, and **Phase 2 / Phase 3 are skipped** until a non-empty transcript exists (fix the model/audio or delete partial temp files and re-run).

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

Run a fast end-to-end smoke test (final outputs capped to 5 seconds):

```bash
python main.py ~/Videos/lectures --quick-test
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

The tool processes videos sequentially through **four** main stages:

### 1. Silence Detection & Trimming

- Analyzes audio track using FFmpeg's `silencedetect` filter
- Identifies silence segments based on configured threshold and duration
- Removes silence while preserving padding around segments
- For phase 1 transcription snippets, a fixed single sweep is used: `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`), and the same shared edge normalization helper as final trim.
- Leading and trailing edge silences are re-scanned at `EDGE_RESCAN_THRESHOLD_DB` (`-55dB`) for both target and non-target final trim runs, then only the edge windows are replaced and reduced to a `EDGE_SILENCE_KEEP_SEC` (200ms) buffer before pad calculations.
- Final encoded MP4s are written under **`output/`** (sibling to the input directory). Intermediate artifacts (snippets, transcripts, titles, FFmpeg scripts, title PNGs, fonts cache) live under **`output/temp/`** — see **Directory Structure** below.

**Target Length Mode**: When `--target-length` is specified, the tool automatically calculates optimal padding to get as close as possible to the target duration.

### 2. Audio Extraction

- **Snippet** (`packages/sr_snippet/`): extracts up to 3 minutes (`SNIPPET_MAX_DURATION_SEC` = 180s) of silence-removed snippet audio for transcription using the same edge policy as final trim (`build_trim_plan` in `src/media/trim.py`).
- Saves as `.ogg` (Opus) under `output/temp/snippet/` (see `get_snippet_path` / `AUDIO_FILE_EXT`)
- Phase-1 snippet extraction ignores `--noise-threshold`/`--min-duration` overrides and always uses `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`) via snippet defaults.
- Reuses existing audio files if already extracted

### 3. Transcription & Title Generation

- **Transcription** (`packages/sr_transcription/`): Transcribes **audio files only** (Phase 1 passes the snippet `.ogg`; `transcribe_media` rejects non-audio extensions). OpenRouter API (default model: `google/gemini-3.1-flash-lite-preview`). Optimized for Arabic verbatim transcription.
- **Title** (`packages/sr_title/`): Generates a YouTube-style title from transcript text.
- Both use a shared OpenRouter transport (`packages/openrouter_transport/`). Pipeline orchestration is in `src/app/pipeline.py`.
- **Two-step process**: Separate API calls for transcription and title generation (better quality and control). Transcript and title are stored in `output/temp/transcript/{basename}.txt` and `output/temp/title/{basename}.txt`.
- **Title extraction constraints**:
  - Output is exactly one Arabic title line (no commentary).
  - The title must be a verbatim contiguous span from the transcript.
  - The title is extracted from the opening complete-sentence portion at the start of the transcript (title-intro area), not from later answer/explanatory body text.
  - The model produces a small pool of candidate titles in **one** generation call (JSON array of distinct titles). A **second** call scores every candidate in one shot (`verbatim_score` and `correctness_score`, each 0–10); the implementation picks the highest **combined** score (sum). Ties break deterministically (earliest transcript substring match, then length near a practical band, then candidate order).
  - The final title is returned after that scoring step (no further LLM calls).

### 4. Title overlay & file renaming (Phase 3)

- The title text from `output/temp/title/{basename}.txt` is loaded right before output encoding.
- `ffprobe` reads the source **video width and height**. A **banner-sized** RGBA PNG (`video_width` × `banner_height`, with `banner_height = (1/6) × frame height`) is written to `output/temp/title_overlays/{basename}.png`. FFmpeg composites it at `x=0`, `y=(1/6) × frame height` (`overlay=0:{y}`), so the strip covers **`y` from H/6 to H/3** (the second sixth of the frame). Values come from `TITLE_BANNER_START_FRACTION` and `TITLE_BANNER_HEIGHT_FRACTION` in `src/core/constants.py`.
- The PNG is rendered by **`packages/sr_title_overlay/`** (`build_title_overlay`): semi-transparent black strip (default alpha **0.5** in that package) with **white** title text in Pillow using the selected `--title-font` (Google Font, cached under `output/temp/fonts/`).
- **Layout algorithm** (largest font that fits, optional multi-line word-boundary splits, bbox-based metrics, vertical stacking): see **`ALGO.md` → “Title overlay PNG”** and tunables in `packages/sr_title_overlay/constants.py`.
- **Arabic / RTL titles**: Pillow draws in visual order only; text is shaped with `arabic-reshaper` and reordered with `python-bidi` (`get_display`) before measuring and drawing. Mixed Arabic + Latin/numbers follow Unicode bidirectional rules.
- FFmpeg applies this PNG in the trim/concat filter graph; no `drawtext` dependency for the final overlay.
- **Logo (optional):** If `logo/logo.png` exists at the **repository root** (that folder is often gitignored), Phase 3 adds another looping PNG input to FFmpeg. **Input order** (0-based): **`0`** = source video, **`1`** = title overlay PNG (when a title is rendered), **`2`** = logo PNG when **both** title and logo are used (the logo is the **third** demuxer input in that case). If `trim_single_video` is called **without** a title but with a logo file, the logo is **`1`**. The pipeline’s Phase 3 always supplies a title, so production runs use **title at `1`, logo at `2`**. **Stacking:** the logo is composited onto the video first, then the title strip on top. `ffprobe` reads the logo width, then a tiny FFmpeg decode (`-frames:v 1` to null) confirms the PNG is readable by the same decoder used in the final command; if either check fails, the logo overlay is skipped with a console warning and the rest of the encode continues. The logo is scaled uniformly with `scale=w=iw*{target}/logo_w:h=ih*{target}/logo_w` where **`target = video_width × LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO`** (default **1.0**, full frame width). After `format=rgba`, **`colorchannelmixer=aa=LOGO_OVERLAY_ALPHA`** (default **1.0**, fully opaque gain) applies before compositing **top-aligned** with **`LOGO_OVERLAY_MARGIN_PX`** inset (default **0**, no padding). Constants live in `src/core/constants.py` (`DEFAULT_LOGO_PATH`, `LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO`, `LOGO_OVERLAY_MARGIN_PX`, `LOGO_OVERLAY_ALPHA`). Stream-copy skips when a logo file is present (same as title overlay).

- Reads generated title from `output/temp/title/{basename}.txt`
- Sanitizes filename (removes invalid characters)
- Handles duplicate names by appending `_N` suffix
- Writes the final trimmed MP4 into **`output/`** (alongside `output/temp/`) with the new title-based filename

## Directory Structure

After processing, your directory structure will look like this:

```
input-directory/
  ├── video1.mp4
  ├── video2.mkv
  └── ...

output/                    # Sibling to input-directory
  ├── generated-title-1.mp4
  ├── generated-title-2.mkv
  └── temp/                # All pipeline intermediates (see bootstrap: temp_dir = output / "temp")
      ├── snippet/         # Silence-removed snippets for transcription
      ├── transcript/      # Transcript text files
      ├── title/           # Title text files
      ├── completed/       # Completion markers
      ├── title_overlays/  # Rendered title PNGs for FFmpeg
      ├── fonts/           # Cached Google Fonts for title rendering
      ├── scripts/         # Temporary ffmpeg filter_complex scripts (cleaned up automatically)
      └── ...
```

## Process Tracking

The tool maintains state in files under **`output/temp/`** to avoid reprocessing videos:

- **Per-video markers**: `output/temp/transcript/{basename}.txt`, `output/temp/title/{basename}.txt`, and `output/temp/completed/{basename}.txt`
- **Automatic Skip**: Phase 1 is skipped if `output/temp/transcript/{basename}.txt` exists **and** contains non-whitespace text; Phase 2 is skipped if title exists; Phase 3 is skipped when the completed marker exists. (Whitespace-only or unreadable transcript files are treated as **not** done for Phase 1.)
- **Manual Reset**: Delete corresponding files under `output/temp/transcript`, `output/temp/title`, and `output/temp/completed` to reprocess specific videos.

## Supported Formats

**Video Extensions**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.3gp`, `.ogv`, `.ts`, `.m2ts`

## API Rate Limiting & Model Selection

The tool includes built-in retry logic for rate limit errors (exponential backoff) and processes videos sequentially to respect API quotas.

- **Defaults**: Transcription, title, and snippet constants default via `src/core/constants.py` (e.g. `OPENROUTER_DEFAULT_MODEL`, `SNIPPET_*`; see `packages/sr_transcription/`, `packages/sr_title/`, `packages/sr_snippet/`). Title PNG layout tunables live in `packages/sr_title_overlay/constants.py`.

## Domain Package Layout

The main code lives under `src/` and `packages/`:

- `src/core`: shared constants, config loading, path utilities, and CLI utilities.
- `src/media`: silence detection, `build_trim_plan` / `trim_single_video`, and related algorithms.
- `src/llm`: re-exports `sr_transcription` and `sr_title` entrypoints and prompts (no separate FFmpeg extraction module).
- `packages/sr_snippet/`: silence-removed transcription snippet audio (`create_silence_removed_snippet`; import as `sr_snippet`).
- `packages/sr_transcription/`: audio transcription API using OpenRouter (import as `sr_transcription`).
- `packages/sr_title/`: transcript-to-title generation using OpenRouter (import as `sr_title`).
- `packages/sr_title_overlay/`: Pillow/Google Fonts PNG title strip for FFmpeg burn-in (import as `sr_title_overlay`).
- `packages/openrouter_transport/`: shared OpenRouter transport layer (import as `openrouter_transport`).
- `src/app`: high-level pipeline orchestration (`run` entrypoint).
- `src/title_editor`: FastAPI title editor UI and standalone server runner.
- `src/ffmpeg`: centralized FFmpeg command construction, probing, execution, filter-graph helpers, and `silence_removed_runner` (shared encode orchestration for silence-removed audio/video paths).
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
