"""Audio extraction for LLM transcription (FFmpeg only - no OpenRouter calls)."""

from pathlib import Path

from src.core.constants import AUDIO_EXTENSIONS, AUDIO_FILE_EXT, SNIPPET_MAX_DURATION_SEC
from src.ffmpeg.core import print_ffmpeg_cmd
from src.ffmpeg.runner import run
from src.ffmpeg.transcode import build_first_5min_audio_ogg_command


def extract_first_5min_audio(input_video: Path, output_audio: Path, format: str = "ogg") -> None:
    """Extract a bounded opening audio window from video for transcription (OGG/Opus).

    Window length matches the FFmpeg builder default: `SNIPPET_MAX_DURATION_SEC` (180s by default).

    Args:
        input_video: Input video file
        output_audio: Output audio file path
        format: Audio format. Must be "ogg".
    """
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    if format != "ogg":
        raise ValueError("Only OGG format is supported for transcription extraction. Use format='ogg'.")

    cmd = build_first_5min_audio_ogg_command(input_video=input_video, output_audio=output_audio)
    print_ffmpeg_cmd(cmd)
    result = run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed for {input_video}\nstderr={result.stderr}"
        )


def get_audio_path_for_media(media_path: Path, temp_dir: Path, basename: str) -> Path:
    """Resolve audio path for transcription: use media_path if audio, else extract opening window to temp_dir.

    Args:
        media_path: Video or audio file path
        temp_dir: Directory for extracted audio when media_path is video
        basename: Base name for extracted file (e.g. stem of video)

    Returns:
        Path to audio file to transcribe
    """
    if media_path.suffix.lower() in AUDIO_EXTENSIONS:
        print(f"Using audio directly (no extraction): {media_path.name}")
        return media_path.resolve()
    audio_path = temp_dir / f"{basename}{AUDIO_FILE_EXT}"
    if not audio_path.exists():
        print(f"Extracting audio (first {SNIPPET_MAX_DURATION_SEC:g}s) -> {audio_path}")
        extract_first_5min_audio(media_path, audio_path, format="ogg")
    else:
        print("Audio already exists (skipping extraction).")
    return audio_path


__all__ = [
    "extract_first_5min_audio",
    "get_audio_path_for_media",
]