"""Common utilities for video processing: constants and core trimming functions.

Style Guide:
============

This module follows the project's coding standards:

1. **Imports**:
   - All imports must be at the top of the file (no lazy imports)
   - Group imports: standard library, third-party, local
   - Use absolute imports
   - Fail early on missing dependencies with clear error messages

2. **Type Hints**:
   - Use type hints for all function parameters and return values
   - Use `Optional[T]` for nullable types
   - Use `Path` from `pathlib` for file paths
   - Use `list[T]` and `tuple[T, ...]` for collections

3. **Naming Conventions**:
   - Constants: UPPER_SNAKE_CASE (e.g., `MAX_PAD_SEC`)
   - Functions: snake_case (e.g., `calculate_resulting_length`)
   - Private functions: prefix with underscore (e.g., `_choose_hwaccel`)
   - Module-level constants grouped with section comments

4. **Function Design**:
   - Functions should be pure (no side effects) when possible
   - Functions should be modular and easily testable
   - Use descriptive function names that explain what they do
   - Include comprehensive docstrings with Args and Returns sections

5. **Error Handling**:
   - Fail fast with clear error messages
   - Use exceptions for error conditions, not return codes
   - Provide context in error messages

6. **FFmpeg Commands**:
   - Always use `build_ffmpeg_cmd()` helper function
   - Always include `-hide_banner` flag
   - Use hardware acceleration when available
   - Handle fallback scenarios gracefully

7. **Code Organization**:
   - Use section comments: `# --- Section Name ---`
   - Group related constants together
   - Group related functions together
   - Keep functions focused on a single responsibility

8. **Documentation**:
   - Module-level docstring describes purpose and style guide
   - Function docstrings use Google-style format
   - Include examples in docstrings where helpful
   - Document edge cases and assumptions

9. **Testing**:
   - Pure functions (no I/O) should be easily unit-testable
   - Functions with I/O should accept dependencies for mocking
   - Test edge cases and error conditions
"""

import re
import subprocess
from pathlib import Path

# --- Constants ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"
PREFERRED_VIDEO_ENCODERS = [
    "hevc_qsv",
    "h264_qsv",
    "h264_videotoolbox",
    "h264_amf",
]
COOLDOWN_BETWEEN_API_CALLS_SEC = 2.0
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "google/gemini-2.0-flash-lite-001"

TRANSCRIBE_PROMPT = """Transcribe the audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = (
    "You are generating a YouTube video title in Arabic.\n"
    "Constraints:\n"
    "- Propose exactly one concise title (<= 100 characters).\n"
    "- Prefer using words verbatim from the transcript wherever possible.\n"
    "- No quotes, no extra commentary. Title only.\n"
    "- When a certain book is mentioned in the transcript as the book being taught, use the book name in the title using the following format: (book name) (title)."
    "- When a lesson number is mentioned in the transcript as the lesson being taught, use the lesson number in the title using the following format: (lesson number) (book name) (title).\n"
    """ِAVOID REPEATING THE NUMBER IN TEXT FORM in the title after the book name. the number can only be in the beginning as shown below.

EXAMPLES:
41 - ألفية ابن مالك - النحو الفاعل واحكامه
42 - الكوكب الساطع - الكناية والتعريض واحكامهما ولمحة عن الحروف
73 - كنز الدقائق - التولية والمرابحة والتصرف في المبيع قبل قبضه
43 - الكوكب الساطع - معاني اذا وان واو واي
9 - العقيدة الطحاوية - القران قديم ام مخلوق ومذاهب الناس في ذلك
9 - أحكام القرآن - احكام الدم و دم سيدنا رسول الله صلى الله عليه وسلم
9 - الموطأ - فضل الجهاد واحكام الجنائز
10 - العقيدة الطحاوية - كيف تسربت الوثنية الى الاديان اليهودية والمسيحية والاسلام ورؤية الله تعالى يوم القيامة
10 - احكام القران - تفسير اية الحيض واختلاف الفقهاء فيها
10 - موطأ الإمام مالك - أحكام الزكاة.\n"""
    "- When no book or lesson number is mentioned, use the title as is.\n"
    "\n\n"
    "Transcript:\n{transcript}\n"
)

COMBINED_TRANSCRIBE_AND_TITLE_PROMPT = """Please perform two tasks:

1. TRANSCRIBE: Transcribe the audio as clean verbatim text in Arabic.
   - No timestamps
   - No speaker labels
   - Keep punctuation and natural phrasing

2. TITLE: Generate a YouTube video title in Arabic based on the transcript.
   - Exactly one concise title (<= 100 characters)
   - Prefer using words verbatim from the transcript wherever possible
   - No quotes, no extra commentary. Title only.
   - When a book is mentioned, use format: (book name) (title)
   - When a lesson number is mentioned, use format: (lesson number) (book name) (title)
   - Avoid repeating numbers in text form after the book name

EXAMPLES:
41 - ألفية ابن مالك - النحو الفاعل واحكامه
42 - الكوكب الساطع - الكناية والتعريض واحكامهما ولمحة عن الحروف
73 - كنز الدقائق - التولية والمرابحة والتصرف في المبيع قبل قبضه
9 - العقيدة الطحاوية - القران قديم ام مخلوق ومذاهب الناس في ذلك
10 - احكام القران - تفسير اية الحيض واختلاف الفقهاء فيها

Please format your response EXACTLY as follows:

TRANSCRIPT:
[your transcription here]

TITLE:
[your title here]"""

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}


# --- FFmpeg Command Builder ---

def build_ffmpeg_cmd(overwrite: bool = True, hwaccel: str | None = None, *additional_flags: str) -> list[str]:
    """Build a base FFmpeg command with common flags.
    
    Args:
        overwrite: If True, add -y flag to overwrite output files
        hwaccel: Optional hardware acceleration method name
        *additional_flags: Additional flags to append to the command
        
    Returns:
        List of command arguments starting with 'ffmpeg'
        
    Example:
        >>> cmd = build_ffmpeg_cmd(overwrite=True, hwaccel="videotoolbox")
        >>> cmd += ["-i", "input.mp4", "-c:v", "libx264", "output.mp4"]
    """
    cmd = ["ffmpeg", "-hide_banner"]
    if overwrite:
        cmd.append("-y")
    if hwaccel:
        cmd.extend(["-hwaccel", hwaccel])
    cmd.extend(additional_flags)
    return cmd


# --- Core Trimming Functions ---

def calculate_resulting_length(silence_starts: list[float], silence_ends: list[float], duration_sec: float, pad_sec: float) -> float:
    """Calculate the resulting video length after trimming silences with padding.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        pad_sec: Padding to retain around silences in seconds
        
    Returns:
        Total length of segments to keep in seconds
    """
    if len(silence_starts) != len(silence_ends):
        if len(silence_starts) > len(silence_ends):
            silence_ends = list(silence_ends) + [duration_sec]
        else:
            silence_ends = list(silence_ends)
    segments_to_keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_end - silence_start <= pad_sec * 2:
            continue
        if silence_start > prev_end:
            segment_start = round(prev_end, 3)
            segment_end = round(silence_start, 3)
            segments_to_keep.append((segment_start, segment_end))
        prev_end = max(0.0, silence_end - pad_sec)
    if prev_end < duration_sec:
        segments_to_keep.append((round(prev_end, 3), round(duration_sec, 3)))
    return sum(end - start for start, end in segments_to_keep)


def find_optimal_padding(silence_starts: list[float], silence_ends: list[float], duration_sec: float, target_length: float) -> float:
    """Find the optimal padding value to achieve a target video length.
    
    Args:
        silence_starts: List of silence start times in seconds
        silence_ends: List of silence end times in seconds
        duration_sec: Total video duration in seconds
        target_length: Desired resulting video length in seconds
        
    Returns:
        Optimal padding value in seconds
    """
    if not silence_starts:
        return 0.0
    result_with_0 = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)
    if target_length >= duration_sec:
        return 0.0
    if result_with_0 > target_length:
        return 0.0
    max_pad = MAX_PAD_SEC
    pad_increment = PAD_INCREMENT_SEC
    current_pad = 0.0
    best_pad = 0.0
    while current_pad <= max_pad:
        resulting_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, current_pad)
        if resulting_length < target_length:
            best_pad = current_pad
        else:
            break
        current_pad += pad_increment
    return round(best_pad, 3)


def choose_hwaccel() -> str | None:
    """Choose the best available hardware acceleration method for FFmpeg.
    
    Returns:
        Hardware acceleration method name, or None if none available
    """
    try:
        cmd = build_ffmpeg_cmd(overwrite=False)
        cmd.append("-hwaccels")
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
    except Exception:
        return None
    preferred = ["videotoolbox", "cuda", "qsv", "d3d11va", "dxva2", "vaapi"]
    available = {line.strip() for line in out.splitlines() if line.strip() and not line.startswith("Hardware acceleration methods")}
    for hw in preferred:
        if hw in available:
            return hw
    return None


def detect_silence_points(input_file: Path, noise_threshold: float, min_duration: float, debug: bool = False) -> tuple[list[float], list[float]]:
    """Detect silence points in a video file using FFmpeg's silencedetect filter.
    
    Args:
        input_file: Path to input video file
        noise_threshold: Noise threshold in dB for silence detection
        min_duration: Minimum duration in seconds for a silence to be detected
        debug: If True, print debug information
        
    Returns:
        Tuple of (silence_starts, silence_ends) lists in seconds
    """
    silence_filter = f"silencedetect=n={noise_threshold}dB:d={min_duration}"

    hwaccel = choose_hwaccel()
    cmd = build_ffmpeg_cmd(overwrite=True, hwaccel=hwaccel)
    # Audio-only analysis: skip video/subtitle/data decoding for speed
    cmd.extend(["-vn", "-sn", "-dn", "-i", str(input_file), "-map", "0:a:0", "-af", silence_filter, "-f", "null", "-"])

    result = subprocess.run(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
    ).stderr
    if debug:
        print(f"[debug] silencedetect filter: {silence_filter}")
        if hwaccel:
            print(f"[debug] using hwaccel: {hwaccel}")
        print(f"[debug] ffmpeg cmd: {' '.join(cmd)}")
        print(f"[debug] Raw FFmpeg silencedetect output (showing lines with 'silence_'):")
        for line in result.splitlines():
            if "silence_" in line:
                print(f"[debug] {line}")
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    if debug:
        print(f"[debug] Parsed counts: starts={len(silence_starts)} ends={len(silence_ends)}")
        if silence_starts:
            print(f"[debug] First start={silence_starts[0]} last start={silence_starts[-1]}")
        if silence_ends:
            print(f"[debug] First end  ={silence_ends[0]} last end  ={silence_ends[-1]}")
        print(f"[debug] Parsed silence_starts={silence_starts[:10]}{'...' if len(silence_starts)>10 else ''}")
        print(f"[debug] Parsed silence_ends  ={silence_ends[:10]}{'...' if len(silence_ends)>10 else ''}")
    return silence_starts, silence_ends

