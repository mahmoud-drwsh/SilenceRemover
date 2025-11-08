# SilenceRemover

Tooling to trim silences from videos, optionally transcribe the first 5 minutes with Gemini, generate a YouTube-style title, and rename files accordingly.

## Requirements
- Python 3.9+
- FFmpeg and FFprobe available on PATH
- Optional (for transcribe/title features):
  - Google GenAI SDK (`google-genai`)
  - `GEMINI_API_KEY` set in environment (use a `.env` file or export)

## Install
This project uses `uv`/PEP 517. Typical install:
```bash
pip install -e .
```
Or run directly with your Python if deps are satisfied.

## Environment
Create a `.env` (or export env vars) to tweak detection parameters and API keys:
```env
# FFmpeg silencedetect parameters
NOISE_THRESHOLD=-30.0  # dB
MIN_DURATION=0.5       # seconds
PAD=0.5                # seconds of padding retained around silences

# Google Gemini
GEMINI_API_KEY=your_key_here
```

## CLI
```bash
python main.py <command> [options]
```

### Commands
- trim: Trim silences from all videos in a folder.
  - Inputs from `<input-dir>`; outputs to a sibling folder `trimmed/`.
  - Options:
    - `--input-dir DIR` (required)
    - `--target-length FLOAT` (optional; tries to find padding to get close to target)

- transcribe: Extract first 5 minutes of audio, transcribe with Gemini, and produce a title.
  - Uses `temp/` to store `.m4a`, transcript `.txt`, and title `.title.txt` files.
  - Options:
    - `--input-dir DIR` (required)
    - `--force` (recreate audio/transcript/title even if existing)

- rename: Copy trimmed videos into `renamed/` using titles from `temp/`.
  - Reads from `trimmed/` and writes to `renamed/`.
  - Options:
    - `--input-dir DIR` (required)

- transcribe-rename: Transcribe first 5 minutes and then rename originals (no trimming).
  - Reads videos directly from the input folder and copies them to `renamed/` using titles from `temp/`.
  - Options:
    - `--input-dir DIR` (required)
    - `--force` (recreate audio/transcript/title even if existing)

- all: Run trim → transcribe → rename.
  - Options:
    - `--input-dir DIR` (required)
    - `--target-length FLOAT`
    - `--force`

## Examples
Trim a folder of videos:
```bash
python main.py trim --input-dir /path/to/videos
```

Transcribe and title (no trimming or renaming):
```bash
python main.py transcribe --input-dir /path/to/videos
```

Rename using titles, copying from trimmed output:
```bash
python main.py rename --input-dir /path/to/videos
```

Transcribe then rename originals (skip trimming):
```bash
python main.py transcribe-rename --input-dir /path/to/videos
```

Run the full pipeline:
```bash
python main.py all --input-dir /path/to/videos
```

## Notes
- Supported video extensions include `.mp4`, `.mkv`, `.mov`, `.webm`, and others defined in `main.py`.
- Hardware-accelerated encoders (e.g., `h264_videotoolbox`, `h264_qsv`) are used when available; otherwise falls back to `libx264`.


