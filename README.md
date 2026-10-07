# SilenceRemover

An automated video processing tool that removes silence segments, transcribes audio content, and intelligently renames videos using AI-generated titles. Optimized for Arabic content with support for educational video formats.

## Features

- **Silence Detection & Removal**: Automatically detects and trims silence segments using FFmpeg's `silencedetect` filter
- **Smart Trimming**: Optional target length optimization that adjusts padding to achieve desired video duration
- **AI Transcription**: Builds a silence-removed snippet (capped at `SNIPPET_MAX_DURATION_SEC`, 180s / 3 minutes by default), encodes it as Ogg/Opus, and transcribes via OpenRouter (default model: `google/gemini-3.1-flash-lite-preview`)
- **Intelligent Renaming**: Generates YouTube-style titles from transcripts and renames files accordingly
- **Process Tracking**: Skips already-processed videos to avoid redundant work
- **Video encoding**: Final MP4 video prefers **`hevc_qsv`** (Intel Quick Sync HEVC) using ICQ (`-global_quality 19`, `-preset medium`, `-g 250`). On QSV runs, command assembly applies conservative QSV device flags (`-init_hw_device qsv`, `-filter_hw_device`) and retries once on the generic path if initialization fails at runtime. If `hevc_qsv` is not available, the pipeline tries **`hevc_amf`** (AMD hardware encoding with `-rc qvbr -qvbr_quality_level 18 -g 250`). If both hardware encoders are unavailable, startup falls back to **`libx265`** (`-crf 30`, `-preset medium`). If hardware encoders are listed but probe encode fails, startup fails fast so the runtime/build issue can be fixed explicitly. All profiles use `-tag:v hvc1 -movflags +faststart` for compatibility.
- **FFmpeg Centralization**: Consolidates command building, execution, probing, and filter graph generation under the new `src/ffmpeg` package.

## Requirements

- **Python**: 3.11 or higher
- **FFmpeg & FFprobe**: Must be on your PATH. Prefer an FFmpeg build with **`hevc_qsv`** (Intel Quick Sync) plus Intel runtime support for the primary encoder path. If you have an AMD GPU with Radeon graphics, **`hevc_amf`** provides hardware acceleration. Also include **`libx265`** for software fallback when hardware encoders are unavailable.
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

### Telegram (optional)

During the **final encode**, the pipeline can send **plain text** Telegram messages when **final encoding starts** and again when it **finishes successfully** (no file upload). Set both of the following in `.env` (alongside your OpenRouter key):

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_or_channel_id
```

The message includes the video index/total, the input filename, title, and output `.mp4` basename. Text is capped at Telegram's **4096** character limit. Failures are logged to stderr and **do not** fail the encode.

Optional: `TELEGRAM_API_BASE` overrides the API host (default `https://api.telegram.org`), e.g. for a self-hosted Bot API server. Treat the bot token as a **secret**.

### Media Manager (optional)

For integration with the external Media Manager service (VPS-based), set the full URL including token and project path:

```env
MEDIA_MANAGER_URL=https://your-server.com/TOKEN/your-project/
```

The system makes one video for each original: the **no-overlay video**. This video has no title banner, no logo, and no subtitles. The title goes into the video metadata.

When `MEDIA_MANAGER_URL` is set, the PC pipeline only uploads the immutable originals. The Media Manager queues each verified original, and the server worker (`remote-js/Dockerfile.worker`) makes the review audio and the no-overlay video. The vertical launcher uses this path.

With `--local-title-and-trim-only` (horizontal recordings), the work stays on the PC. The pipeline runs these phases (numbers as in `src/app/pipeline.py`):

- **Phase 0, Trim Script Generation**: Make reusable final-video and snippet-audio FFmpeg trim scripts from silence detection and the trim policy.
- **Phase 1, Snippet Creation**: Make the silence-removed snippet for transcription from the trim script.
- **Phase 2, Transcription**: Transcribe the snippet. When `MEDIA_MANAGER_URL` is set, the Media Manager analyzes the snippet transiently and returns the transcript and the title. Otherwise the PC calls OpenRouter.
- **Phase 3, Title Generation**: Make the title from the transcript.
- **Phase 8, Final Encode**: Make the no-overlay video. The encode writes the title into the video metadata. The copy shortcut also writes the metadata title.

This mode does no Media Manager upload. Without `MEDIA_MANAGER_URL` and without the local flag, the pipeline also lists Phase 4 (Original Upload), Phase 5 (Audio Upload) and Phase 12 (No-Overlay Upload), but these phases skip with "media manager disabled".

The pipeline does not pull edited titles back from the Media Manager.

## Usage

### Basic Usage

Process all videos in a directory:

```bash
python main.py /path/to/video/directory
```

### Options

- `--target-length FLOAT`: Target length in seconds for final output. This enables a fixed internal two-stage search: threshold `-60.0..-35.0 dB` on a `0.1 dB` grid, `0.100s` minimum silence detection, and padding search from `0.060s` in `0.01s` increments.
- `--non-target-noise-threshold FLOAT`: Override silence detection threshold in dB for non-target mode. Ignored when `--target-length` is set.
- `--non-target-min-duration FLOAT`: Override minimum silence duration in seconds for non-target mode. Ignored when `--target-length` is set.
- `--non-target-pad-sec FLOAT`: Override padding in seconds for non-target mode. Ignored when `--target-length` is set.
- `--encoder {QSV,VAAPI,AMF,X265}`: Select the video encoder.
- `--skip-shorter-than FLOAT`: Move videos shorter than this duration to `input/ignored/` before processing.
- `--local-title-and-trim-only`: Run only the local trim, snippet, transcription, title generation, and one silence-removed encode. Do no uploads.

The pipeline has no title-overlay, logo-overlay, or title-font options. The final video never has a title banner or a logo.

**Video-only files (no audio stream):** Some exports are silent (video track only). The pipeline detects missing audio with ffprobe, skips `silencedetect` (which would otherwise fail on `-map 0:a:0`), generates a **silent** transcription snippet from the video duration, and muxes **silent stereo** from `anullsrc` during the final trim/encode when a full encode runs. **Transcription** still calls OpenRouter on that snippet; if the model returns **empty or whitespace-only** text, **no** `output/temp/transcript/{basename}.txt` is written, Phase 2 fails for that video, and **subsequent phases are skipped** until a non-empty transcript exists (fix the model/audio or delete partial temp files and re-run).

Trimming precision controls (advanced):

- `src/core/constants.py`: `TRIM_DECIMAL_PLACES` controls timestamp precision used when calculating and applying segment boundaries (default `6`).
- `src/core/constants.py`: `TRIM_TIMESTAMP_EPSILON_SEC` controls floating-point under-target tolerance in length checks.

### Examples

Process videos with target length optimization:

```bash
python main.py ~/Videos/lectures --target-length 600
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

The tool processes videos sequentially through the phases listed above. The main stages are:

### 1. Silence Detection & Trimming

- Analyzes audio track using FFmpeg's `silencedetect` filter
- Identifies silence segments based on configured threshold and duration
- Removes silence while preserving padding around segments
- For phase 1 transcription snippets, a fixed single sweep is used: `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`), and the same shared edge normalization helper as final trim.
- Leading and trailing edge silences are re-scanned at `EDGE_RESCAN_THRESHOLD_DB` (`-40dB`) for both target and non-target final trim runs, then only the edge windows are replaced and reduced to a `EDGE_SILENCE_KEEP_SEC` (200ms) buffer before pad calculations.
- Final encoded MP4s are written under **`output/`** (sibling to the input directory). Intermediate artifacts (snippets, transcripts, titles, FFmpeg scripts) live under **`output/temp/`** — see **Directory Structure** below.

**Target Length Mode**: When `--target-length` is specified, the tool uses a fixed two-stage binary search. Stage 1 finds the earliest threshold in `[-60.0, -35.0]` whose estimated output at `0.060s` padding is at or under target, using `0.100s` minimum silence detection. Stage 2 reuses those detected silences and increases padding in `0.01s` steps without exceeding target. Because final segment building still keeps `pad_sec` on both sides of a cut silence, the practical removable-silence floor stays around `0.120s`. If even `-35.0 dB` with `0.060s` padding stays over target, the tool returns that best-effort result and does not truncate content.

### 2. Audio Extraction

- **Snippet** (`packages/sr_snippet/`): extracts up to 3 minutes (`SNIPPET_MAX_DURATION_SEC` = 180s) of silence-removed snippet audio for transcription using the same edge policy as final trim (`build_trim_plan` in `packages/sr_trim_plan/`).
- Saves as `.ogg` (Opus) under `output/temp/snippet/` (see `get_snippet_path` / `AUDIO_FILE_EXT`)
- Phase-1 snippet extraction ignores `--non-target-noise-threshold`/`--non-target-min-duration` overrides and always uses `SNIPPET_NOISE_THRESHOLD_DB` (`-55dB`) and `SNIPPET_MIN_DURATION_SEC` (`0.01s`) via snippet defaults.
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

### 4. Final encode & file renaming

- The final encode makes the no-overlay video. It writes the generated title into the video metadata.
- When the trim plan needs no cut, the encode can use a copy shortcut. The shortcut also writes the metadata title.
- The final video has no title banner, no logo, and no subtitle track.

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
      ├── scripts/         # Temporary ffmpeg filter_complex scripts (cleaned up automatically)
      ├── silence/         # Silence detection cache
      ├── processing/      # Video processing intermediates
      └── ...
```

## Process Tracking

The tool maintains state in files under **`output/temp/`** to avoid reprocessing videos:

- **Per-video markers**: `output/temp/trim_scripts/{script_key}.ffscript`, `output/temp/transcript/{basename}.txt`, `output/temp/title/{basename}.txt`, and `output/temp/completed/{basename}.txt`
- **Automatic Skip**: Trim script generation is skipped if the expected final/snippet trim scripts already exist; if only the final script exists from an older cache, the snippet script is derived from it without rerunning silence analysis. snippet creation is skipped if the snippet exists; transcription is skipped if the transcript exists with non-whitespace text; title generation is skipped if the title exists; the upload steps are skipped if the server already has the original or the audio; the final encode is skipped if the completed marker exists; the no-overlay upload is skipped if the local MP4 is missing or the server already has the no-overlay video. See `docs/SKIP_CONDITIONS.yaml`. (Whitespace-only or unreadable transcript files are treated as **not** done for transcription.)
- **Manual Reset**: Delete corresponding files under `output/temp/transcript`, `output/temp/title`, and `output/temp/completed` to reprocess specific videos.

## Supported Formats

**Video Extensions**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.flv`, `.wmv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.3gp`, `.ogv`, `.ts`, `.m2ts`

## API Rate Limiting & Model Selection

The tool includes built-in retry logic for rate limit errors (exponential backoff) and processes videos sequentially to respect API quotas.

- **Defaults**: Transcription, title, and snippet constants default via `src/core/constants.py` (e.g. `OPENROUTER_DEFAULT_MODEL`, `SNIPPET_*`; see `packages/sr_transcription/`, `packages/sr_title/`, `packages/sr_snippet/`).

## Domain Package Layout

The main code lives under `src/` and `packages/`:

- `src/core`: shared constants, config loading, path utilities, and CLI utilities.
- `src/media`: silence detection and final trim rendering (`trim_single_video`).
- `src/app`: high-level pipeline orchestration (`run` entrypoint).
- `src/ffmpeg`: centralized FFmpeg command construction, probing, execution, filter-graph helpers, and `silence_removed_runner` (shared encode orchestration for silence-removed audio/video paths).
- `src/startup`: startup bootstrap and runtime context assembly.

### Black Box Packages (`packages/`)

- `packages/sr_trim_plan/`: shared trim-policy black box (`TrimPlan`, `build_trim_plan`) for snippet + final trim.
- `packages/sr_snippet/`: silence-removed transcription snippet audio (`create_silence_removed_snippet`; import as `sr_snippet`).
- `packages/sr_transcription/`: audio transcription API using OpenRouter (import as `sr_transcription`).
- `packages/sr_title/`: transcript-to-title generation using OpenRouter (import as `sr_title`).
- `packages/openrouter_transport/`: shared OpenRouter transport layer (import as `openrouter_transport`).
- `packages/sr_telegram_notify/`: optional final-encode Telegram text notifications (`notify_final_encoding_started`, `notify_final_output_ready`; import as `sr_telegram_notify`).
- `packages/sr_filename/`: filename sanitization utilities (import as `sr_filename`).
- `packages/sr_ffmpeg_cmd_builder/`: FFmpeg/FFprobe command builders (import as `sr_ffmpeg_cmd_builder`).
- `packages/sr_filter_graph/`: FFmpeg trim and concat filter graph construction (import as `sr_filter_graph`).
- `packages/sr_media_manager/`: Media Manager API client for the pipeline workflow (originals, review audio, and no-overlay video uploads) (import as `sr_media_manager`). Replaces old `sr_mp3_manager`.
- `packages/sr_progress_formatter/`: FFmpeg progress output formatting (import as `sr_progress_formatter`).
- `packages/sr_silence_detection/`: silence detection and interval processing (import as `sr_silence_detection`).
- `packages/sr_threshold_selection/`: threshold selection algorithms (import as `sr_threshold_selection`).

## Error Handling

- **Missing Tools**: Validates FFmpeg/FFprobe availability before processing
- **API Errors**: Automatic retry with exponential backoff
- **Encoding Failures**: Startup selects `hevc_qsv` when available, falls back to `libx265` only when QSV is absent, and otherwise reports FFmpeg errors directly.
- **Invalid Videos**: Skips corrupted or unreadable files with error messages

## Troubleshooting

### FFmpeg not found

Ensure FFmpeg and FFprobe are installed and available on your PATH:

```bash
ffmpeg -version
ffprobe -version
```

Note: This project’s shared FFmpeg command builder (`src/ffmpeg/core.py:add_filter_complex_script`) uses the non-deprecated filter graph script option `-/filter_complex`, so you should no longer see the `-filter_complex_script is deprecated` warning in normal runs.

### Slow QSV encodes

If `hevc_qsv` is selected but throughput is still low:

- Confirm the printed final command includes the QSV device flags (`-init_hw_device qsv=...`, `-filter_hw_device`). If those flags fail on your machine, the pipeline logs a warning and retries on the generic path.
- For quick command-level sanity, run `python tests/ffmpeg_api_smoke.py` and check the QSV hardware-path assertions.

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

## Manual production black-box check

Run this only when an explicit production verification is needed; it is not part of CI or deployment. The command downloads one bounded existing original, uploads a 25-second copy, waits for review analysis, approves a unique test title, verifies the no-overlay video and its original link, then trashes and deletes every test artifact even after a failure.

It needs the normal `MEDIA_MANAGER_URL` project credential and incurs one review-analysis request. Develop and validate the harness locally with the isolated Docker flow first; use production only for the final confirmation.

The lifecycle is also testable without credentials, network access, Docker, or
OpenRouter. Run the deterministic fake-backed checks with:

```bash
.venv/bin/pytest -q tests/test_black_box_source_processing.py
```

The production command remains manual and requires `--confirm-production`; it
is not invoked by tests, CI, or deployment.
Cleanup performs bounded retries and a final readback stabilization pass so
artifacts published late by an in-flight worker are still removed.

The `check_id` endpoint uses two success shapes: a missing file returns
`{"exists": false}`, while a stored file returns its normal file response
without an `exists` field. Keep the harness predicate compatible with both.
An earlier production acceptance run (before spec #44) verified review/title
approval, subtitle delivery, both served final variants, and a fractional
`25.121` duration; it left no test file rows. Its completed source-processing job remains as normal
historical evidence.

```bash
.venv/bin/python scripts/black_box_source_processing.py \
  --confirm-production --work-dir /tmp/silence-remover-black-box
```
