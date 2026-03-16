"""Phase 1 orchestration: transcribe media to text and generate title."""

from pathlib import Path

from src import title
from src import transcribe


def transcribe_single_video(
    media_path: Path, temp_dir: Path, api_key: str, basename: str
) -> tuple[str, str]:
    """Transcribe from a video or audio file. Returns (transcript_text, title_text).

    If media_path is an audio file (e.g. .wav, .m4a), uses it directly without extraction.
    Otherwise extracts first 5 min of audio from the video.
    Caller is responsible for persisting transcript/title (e.g. in data.json).

    Args:
        media_path: Path to video file or pre-extracted audio (e.g. snippet.wav)
        temp_dir: Temporary directory for intermediate files (e.g. extracted audio)
        api_key: OpenRouter API key
        basename: Base name for temp audio file if extraction is needed

    Returns:
        Tuple of (transcript_text, title_text)
    """
    audio_path = transcribe.get_audio_path_for_media(media_path, temp_dir, basename)

    print("Transcribing with OpenRouter...")
    transcript_text = transcribe.transcribe_with_openrouter(api_key, audio_path)

    print("Generating YouTube title...")
    title_text = title.generate_title_with_openrouter(api_key, transcript_text)

    return transcript_text.strip(), title_text.strip()
