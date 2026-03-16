"""Phase 1 orchestration: transcribe media to text and generate title."""

from pathlib import Path

from src import title
from src import transcribe


def transcribe_media(
    media_path: Path,
    temp_dir: Path,
    api_key: str,
    basename: str,
) -> None:
    """Transcribe from a video or audio file and save transcript to file.

    If media_path is an audio file (e.g. .wav, .m4a), uses it directly without extraction.
    Otherwise extracts first 5 min of audio from the video.

    Args:
        media_path: Path to video file or pre-extracted audio (e.g. snippet.ogg)
        temp_dir: Temporary directory for intermediate files
        api_key: OpenRouter API key
        basename: Base name for temp audio file if extraction is needed
    """
    audio_path = transcribe.get_audio_path_for_media(media_path, temp_dir, basename)

    # Transcript output path
    transcript_path = temp_dir / "transcript" / f"{basename}.txt"

    print("Transcribing with OpenRouter...")
    transcribe.transcribe_and_save(
        api_key=api_key,
        audio_path=audio_path,
        output_path=transcript_path,
        log_dir=temp_dir,
    )


def generate_title(
    temp_dir: Path,
    api_key: str,
    basename: str,
) -> None:
    """Generate title from transcript file and save to file.

    Args:
        temp_dir: Temporary directory containing transcript files
        api_key: OpenRouter API key
        basename: Base name for the video/audio file
    """
    transcript_path = temp_dir / "transcript" / f"{basename}.txt"
    title_path = temp_dir / "title" / f"{basename}.txt"

    print("Generating YouTube title...")
    title.generate_title_from_transcript(
        api_key=api_key,
        transcript_path=transcript_path,
        output_path=title_path,
        log_dir=temp_dir,
    )


def transcribe_single_video(
    media_path: Path, temp_dir: Path, api_key: str, basename: str
) -> tuple[str, str]:
    """Transcribe from a video or audio file. Returns (transcript_text, title_text).

    This is a backward-compatible wrapper that combines transcription and title generation.

    Args:
        media_path: Path to video file or pre-extracted audio (e.g. snippet.ogg)
        temp_dir: Temporary directory for intermediate files
        api_key: OpenRouter API key
        basename: Base name for temp audio file if extraction is needed

    Returns:
        Tuple of (transcript_text, title_text)
    """
    transcribe_media(media_path, temp_dir, api_key, basename)
    generate_title(temp_dir, api_key, basename)

    transcript_path = temp_dir / "transcript" / f"{basename}.txt"
    title_path = temp_dir / "title" / f"{basename}.txt"

    transcript_text = transcript_path.read_text(encoding="utf-8").strip()
    title_text = title_path.read_text(encoding="utf-8").strip()

    return transcript_text, title_text
