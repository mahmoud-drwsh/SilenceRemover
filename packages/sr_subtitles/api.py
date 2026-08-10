"""Create SRT files from retained speech segments without model timestamps."""

from __future__ import annotations

import base64
from pathlib import Path

from openrouter_transport import request as openrouter_request
from src.core.constants import GEMINI_SUBTITLE_MODEL
from src.ffmpeg.core import build_ffmpeg_cmd
from src.ffmpeg.runner import run

DEFAULT_SUBTITLE_MODEL = GEMINI_SUBTITLE_MODEL
SUBTITLE_MIME_TYPE = "application/x-subrip"
MAX_SEGMENTS_PER_CUE = 12

_PROMPT = """Transcribe this Arabic audio verbatim. Output only the transcript text, with no timestamps, labels, Markdown, commentary, or invented words."""


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02},{milliseconds:03}"


def render_srt(segments: list[tuple[float, float]], texts: list[str]) -> str:
    """Render one deterministic cue per retained segment on final-video time."""
    if len(segments) != len(texts) or not segments:
        raise ValueError("Subtitle segments and texts must be non-empty and have equal length")
    lines: list[str] = []
    output_offset = 0.0
    for index, ((start, end), text) in enumerate(zip(segments, texts), start=1):
        clean = " ".join(text.split())
        if not clean or end <= start:
            raise ValueError("Subtitle text must be non-empty and segment duration positive")
        duration = end - start
        lines.extend([str(index), f"{_timestamp(output_offset)} --> {_timestamp(output_offset + duration)}", clean, ""])
        output_offset += duration
    return "\n".join(lines) + "\n"


def _extract_segment_audio(input_file: Path, output_file: Path, start: float, end: float) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cmd(True, "-v", "error", "-ss", f"{start:.6f}", "-i", str(input_file), "-t", f"{end - start:.6f}", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_file))
    run(cmd, capture_output=True)


def _group_segments(segments: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """Bound provider inputs while preserving each group's final-video duration."""
    groups: list[tuple[float, float, float]] = []
    for offset in range(0, len(segments), MAX_SEGMENTS_PER_CUE):
        batch = segments[offset:offset + MAX_SEGMENTS_PER_CUE]
        groups.append((batch[0][0], batch[-1][1], sum(end - start for start, end in batch)))
    return groups


def generate_srt_from_trim_segments(
    *, input_file: Path, segments: list[tuple[float, float]], output_path: Path,
    work_dir: Path, api_key: str, model: str = DEFAULT_SUBTITLE_MODEL, log_dir: Path | None = None,
) -> None:
    """Extract retained speech once, request matching text, and render local timings."""
    if not segments:
        raise RuntimeError("Cannot generate subtitles because the trim plan retained no speech")
    groups = _group_segments(segments)
    texts: list[str] = []
    final_segments: list[tuple[float, float]] = []
    for index, (start, end, final_duration) in enumerate(groups, start=1):
        audio_path = work_dir / f"{index:04}.wav"
        _extract_segment_audio(input_file, audio_path, start, end)
        payload = audio_path.read_bytes()
        if not payload:
            raise RuntimeError(f"Extracted subtitle segment is empty: {audio_path.name}")
        raw = openrouter_request(api_key, model, [{"role": "user", "content": [
            {"type": "text", "text": _PROMPT},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(payload).decode("ascii"), "format": "wav"}},
        ]}], max_output_tokens=1024, log_dir=log_dir)
        text = raw.strip()
        if not text:
            raise RuntimeError("Subtitle model returned empty text")
        texts.append(text)
        final_segments.append((0.0, final_duration))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_srt(final_segments, texts), encoding="utf-8")


def mux_srt_track(video_path: Path, srt_path: Path) -> None:
    """Add a disabled Arabic mov_text track without re-encoding video or audio."""
    replacement = video_path.with_name(f"{video_path.stem}.subtitles.mp4")
    cmd = build_ffmpeg_cmd(True, "-v", "error", "-i", str(video_path), "-i", str(srt_path), "-map", "0", "-map", "1:0", "-c", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=ara", "-disposition:s:0", "0", str(replacement))
    run(cmd, capture_output=True)
    replacement.replace(video_path)
