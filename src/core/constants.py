"""Project-wide constants (non-secret configuration).

This module contains all tunable constants that are not environment-backed.
Secrets (e.g. OPENROUTER_API_KEY) live in src/core/config.py.
"""

from dataclasses import dataclass


# --- Padding / bitrate ---
MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.001
TRIM_DECIMAL_PLACES = 6
TRIM_TIMESTAMP_EPSILON_SEC = 1e-6
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"
EDGE_SILENCE_KEEP_SEC = 0.2

# --- Edge scan defaults ---
EDGE_RESCAN_THRESHOLD_DB = -55.0
EDGE_RESCAN_MIN_DURATION_SEC = 0.01

# --- Non-target mode defaults ---
NON_TARGET_NOISE_THRESHOLD_DB = -50.0
NON_TARGET_MIN_DURATION_SEC = 1.0
NON_TARGET_PAD_SEC = 0.5

# --- Target mode defaults ---

TARGET_NOISE_THRESHOLD_DB = -55.0
TARGET_MIN_DURATION_SEC = 0.01
TARGET_NOISE_THRESHOLDS_DB: list[float] = [
    -60.0,
    -59.0,
    -58.0,
    -57.0,
    -56.0,
    -55.0,
    -54.0,
    -53.0,
    -52.0,
    -51.0,
    -50.0,
    -49.0,
    -48.0,
    -47.0,
    -46.0,
    -45.0,
    -44.0,
    -43.0,
    -42.0,
    -41.0,
    -40.0,
    -39.0,
    -38.0,
    -37.0,
    -36.0,
    -35.0,
    -34.0,
    -33.0,
    -32.0,
    -31.0,
    -30.0
]

# --- Snippet defaults ---

SNIPPET_NOISE_THRESHOLD_DB = TARGET_NOISE_THRESHOLD_DB
SNIPPET_MIN_DURATION_SEC = TARGET_MIN_DURATION_SEC
SNIPPET_MAX_DURATION_SEC = 180.0

# --- Shared runtime defaults ---

@dataclass(frozen=True)
class TrimDefaults:
    """Resolved trim defaults after applying request overrides."""

    noise_threshold: float
    min_duration: float
    pad_sec: float


def resolve_trim_defaults(
    *,
    target_length: float | None,
    noise_threshold: float | None,
    min_duration: float | None,
    pad_sec: float | None = None,
) -> TrimDefaults:
    """Resolve effective trim policy from CLI overrides and mode flags."""
    if target_length is None:
        return TrimDefaults(
            noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB if noise_threshold is None else noise_threshold,
            min_duration=NON_TARGET_MIN_DURATION_SEC if min_duration is None else min_duration,
            pad_sec=NON_TARGET_PAD_SEC if pad_sec is None else pad_sec,
        )

    return TrimDefaults(
        noise_threshold=TARGET_NOISE_THRESHOLD_DB if noise_threshold is None else noise_threshold,
        min_duration=TARGET_MIN_DURATION_SEC if min_duration is None else min_duration,
        pad_sec=NON_TARGET_PAD_SEC if pad_sec is None else pad_sec,
    )


# Compatibility aliases for downstream users and older import paths.
_COMPATIBILITY_CONSTANT_ALIASES = {
    "DEFAULT_NOISE_THRESHOLD": "NON_TARGET_NOISE_THRESHOLD_DB",
    "DEFAULT_MIN_DURATION": "NON_TARGET_MIN_DURATION_SEC",
    "DEFAULT_PAD_SEC": "NON_TARGET_PAD_SEC",
    "SIMPLE_DB": "TARGET_NOISE_THRESHOLD_DB",
    "SIMPLE_MIN_DURATION": "TARGET_MIN_DURATION_SEC",
    "TARGET_MIN_DURATION": "TARGET_MIN_DURATION_SEC",
}

for _alias, _canonical_name in _COMPATIBILITY_CONSTANT_ALIASES.items():
    globals()[_alias] = globals()[_canonical_name]

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
FONTS_DIR = "fonts"
TITLE_OVERLAYS_DIR = "title_overlays"

# --- File extensions ---

AUDIO_EXTENSIONS: frozenset[str] = frozenset({".wav", ".m4a", ".mp3", ".aac", ".ogg", ".flac", ".aiff"})
AUDIO_FORMATS: frozenset[str] = frozenset(ext.lstrip(".") for ext in AUDIO_EXTENSIONS)
AUDIO_FILE_EXT = ".ogg"
TEXT_FILE_EXT = ".txt"

# Vertical sixths: overlay starts at top of 2nd sixth; band height is 2/6 of frame (y in [H/6, H/2]).
TITLE_BANNER_START_FRACTION = 1 / 6
TITLE_BANNER_HEIGHT_FRACTION = 2 / 6
TITLE_BANNER_BG_ALPHA = 0.5
TITLE_FONT_DEFAULT = "Noto Naskh Arabic"
TITLE_MIN_READABLE_FONT_PX = 26
TITLE_MIN_READABLE_FONT_BANNER_FRACTION = 0.12
TITLE_TWO_LINE_MIN_GAIN_PX = 1

__all__ = [
    "TrimDefaults",
    "resolve_trim_defaults",
    "MAX_PAD_SEC",
    "PAD_INCREMENT_SEC",
    "TRIM_DECIMAL_PLACES",
    "TRIM_TIMESTAMP_EPSILON_SEC",
    "BITRATE_FALLBACK_BPS",
    "AUDIO_BITRATE",
    "EDGE_RESCAN_THRESHOLD_DB",
    "EDGE_RESCAN_MIN_DURATION_SEC",
    "NON_TARGET_NOISE_THRESHOLD_DB",
    "NON_TARGET_MIN_DURATION_SEC",
    "NON_TARGET_PAD_SEC",
    "TARGET_NOISE_THRESHOLD_DB",
    "TARGET_MIN_DURATION_SEC",
    "DEFAULT_NOISE_THRESHOLD",
    "DEFAULT_MIN_DURATION",
    "DEFAULT_PAD_SEC",
    "SIMPLE_DB",
    "SIMPLE_MIN_DURATION",
    "SNIPPET_NOISE_THRESHOLD_DB",
    "SNIPPET_MIN_DURATION_SEC",
    "SNIPPET_MAX_DURATION_SEC",
    "TARGET_MIN_DURATION",
    "TARGET_NOISE_THRESHOLDS_DB",
    "VIDEO_EXTENSIONS",
    "SNIPPET_DIR",
    "TRANSCRIPT_DIR",
    "TITLE_DIR",
    "COMPLETED_DIR",
    "SCRIPTS_DIR",
    "FONTS_DIR",
    "TITLE_OVERLAYS_DIR",
    "AUDIO_EXTENSIONS",
    "AUDIO_FORMATS",
    "AUDIO_FILE_EXT",
    "TEXT_FILE_EXT",
    "TITLE_BANNER_START_FRACTION",
    "TITLE_BANNER_HEIGHT_FRACTION",
    "TITLE_BANNER_BG_ALPHA",
    "TITLE_FONT_DEFAULT",
    "TITLE_MIN_READABLE_FONT_PX",
    "TITLE_MIN_READABLE_FONT_BANNER_FRACTION",
    "TITLE_TWO_LINE_MIN_GAIN_PX",
    "EDGE_SILENCE_KEEP_SEC",
]

