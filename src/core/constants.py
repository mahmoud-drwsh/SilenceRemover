"""Project-wide constants (non-secret configuration).

This module contains all tunable constants that are not environment-backed.
Secrets (e.g. OPENROUTER_API_KEY) live in src/core/config.py.
"""

# --- Padding / bitrate ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.001
TRIM_DECIMAL_PLACES = 6
TRIM_TIMESTAMP_EPSILON_SEC = 1e-6
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"

# --- Non-target defaults (used when no CLI override) ---

DEFAULT_NOISE_THRESHOLD = -50.0
DEFAULT_MIN_DURATION = 0.5
DEFAULT_PAD_SEC = 0.5

# --- Target-length / target-mode ---

SIMPLE_DB = -55.0
SIMPLE_MIN_DURATION = 0.01

TARGET_MIN_DURATION = 0.01
TARGET_NOISE_THRESHOLDS_DB: list[float] = [
    -60.0,
    -55.0,
    -50.0,
    -45.0,
    -40.0,
    -35.0,
    -30.0,
    -25.0,
    -20.0,
]

# --- Supported inputs ---

VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
})

# --- Temp subdirectory names ---

SNIPPET_DIR = "snippet"
TRANSCRIPT_DIR = "transcript"
TITLE_DIR = "title"
COMPLETED_DIR = "completed"
SCRIPTS_DIR = "scripts"

# --- File extensions ---

AUDIO_EXTENSIONS: frozenset[str] = frozenset({".wav", ".m4a", ".mp3", ".aac", ".ogg", ".flac", ".aiff"})
AUDIO_FORMATS: frozenset[str] = frozenset(ext.lstrip(".") for ext in AUDIO_EXTENSIONS)
AUDIO_FILE_EXT = ".ogg"
TEXT_FILE_EXT = ".txt"

__all__ = [
    "MAX_PAD_SEC",
    "PAD_INCREMENT_SEC",
    "TRIM_DECIMAL_PLACES",
    "TRIM_TIMESTAMP_EPSILON_SEC",
    "BITRATE_FALLBACK_BPS",
    "AUDIO_BITRATE",
    "DEFAULT_NOISE_THRESHOLD",
    "DEFAULT_MIN_DURATION",
    "DEFAULT_PAD_SEC",
    "SIMPLE_DB",
    "SIMPLE_MIN_DURATION",
    "TARGET_MIN_DURATION",
    "TARGET_NOISE_THRESHOLDS_DB",
    "VIDEO_EXTENSIONS",
    "SNIPPET_DIR",
    "TRANSCRIPT_DIR",
    "TITLE_DIR",
    "COMPLETED_DIR",
    "SCRIPTS_DIR",
    "AUDIO_EXTENSIONS",
    "AUDIO_FORMATS",
    "AUDIO_FILE_EXT",
    "TEXT_FILE_EXT",
]

