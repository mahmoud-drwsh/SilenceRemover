"""Create SRT files from retained speech segments without model timestamps."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from openrouter_transport import request as openrouter_request
from src.core.constants import GEMINI_SUBTITLE_MODEL
from src.ffmpeg.core import build_ffmpeg_cmd
from src.ffmpeg.runner import run

DEFAULT_SUBTITLE_MODEL = GEMINI_SUBTITLE_MODEL
SUBTITLE_MIME_TYPE = "application/x-subrip"
MAX_SEGMENTS_PER_CUE = 12

_PROMPT = """Transcribe this Arabic audio verbatim. Output only the transcript text, with no timestamps, labels, Markdown, commentary, or invented words."""
_SRT_PROMPT = """Transcribe this Arabic video verbatim as SubRip subtitles. Return only valid SRT with sequential numeric cue IDs and timestamps exactly like 00:00:01,250 --> 00:00:04,500 (a comma before exactly three millisecond digits). Keep cues short and readable, never overlap cues, and stay within the supplied media duration. Do not use Markdown or commentary."""


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_part:02},{milliseconds:03}"


def _parse_model_timestamp(value: str) -> float:
    value = value.strip()
    if "," in value:
        clock, milliseconds = value.rsplit(",", 1)
        parts = clock.split(":")
        if len(parts) == 2:
            hours, minutes, seconds = 0, int(parts[0]), int(parts[1])
        elif len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
        else:
            raise ValueError
    else:
        parts = value.split(":")
        if len(parts) == 3:  # Gemini's MM:SS:ms dialect.
            hours, minutes, seconds, milliseconds = 0, int(parts[0]), int(parts[1]), parts[2]
        elif len(parts) == 4:
            hours, minutes, seconds, milliseconds = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
        else:
            raise ValueError
    if not milliseconds.isdigit() or not 1 <= len(milliseconds) <= 3 or minutes >= 60 or seconds >= 60:
        raise ValueError
    return hours * 3600 + minutes * 60 + seconds + int(milliseconds.ljust(3, "0")) / 1000


def validate_model_srt(raw: str, duration: float) -> str:
    """Accept only complete, sequential, non-overlapping cues within the media."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:srt)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    lines = cleaned.splitlines()
    normalized: list[str] = []
    previous_end = 0.0
    cursor = 0
    expected = 1
    while cursor < len(lines):
        while cursor < len(lines) and not lines[cursor].strip(): cursor += 1
        if cursor >= len(lines): break
        if lines[cursor].strip() != str(expected) or cursor + 1 >= len(lines) or "-->" not in lines[cursor + 1]:
            raise RuntimeError("Subtitle model response was not valid SRT")
        left, right = lines[cursor + 1].split("-->", 1)
        try:
            start, end = _parse_model_timestamp(left), _parse_model_timestamp(right)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Subtitle model response contained an invalid timestamp") from exc
        cursor += 2
        text_lines: list[str] = []
        while cursor < len(lines):
            if lines[cursor].strip().isdigit() and cursor + 1 < len(lines) and "-->" in lines[cursor + 1]:
                break
            if lines[cursor].strip(): text_lines.append(lines[cursor].strip())
            cursor += 1
        text = " ".join(" ".join(text_lines).split())
        if not text or start < previous_end or end <= start or end > duration + 0.25:
            raise RuntimeError("Subtitle model SRT failed deterministic timing validation")
        normalized.extend([str(expected), f"{_timestamp(start)} --> {_timestamp(end)}", text, ""])
        previous_end = end
        expected += 1
    if expected == 1:
        raise RuntimeError("Subtitle model response was not valid SRT")
    return "\n".join(normalized) + "\n"


def generate_srt_from_served_video(
    *, input_file: Path, output_path: Path, work_dir: Path, api_key: str,
    duration: float, model: str = DEFAULT_SUBTITLE_MODEL, log_dir: Path | None = None,
) -> None:
    """Generate and guard SRT directly against an already-served video timeline."""
    audio_path = work_dir / "served-timeline.wav"
    _extract_segment_audio(input_file, audio_path, 0.0, duration)
    payload = audio_path.read_bytes()
    prompt = f"{_SRT_PROMPT}\nThe exact media duration is {duration:.3f} seconds."
    raw = openrouter_request(api_key, model, [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(payload).decode("ascii"), "format": "wav"}},
    ]}], max_output_tokens=8192, log_dir=log_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(validate_model_srt(raw, duration), encoding="utf-8")


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
    cmd = build_ffmpeg_cmd(
        True, "-v", "error", "-i", str(video_path), "-i", str(srt_path),
        "-map", "0:v", "-map", "0:a?", "-map", "0:d?", "-map", "1:0",
        "-c", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=ara",
        "-disposition:s:0", "0", "-movflags", "+faststart", str(replacement),
    )
    run(cmd, capture_output=True)
    replacement.replace(video_path)
