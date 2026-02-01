"""Configuration constants and environment variables for video processing."""

from src.env_config import get_config

# --- Trimming Constants ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"

# --- OpenRouter API Configuration ---
# (configurable via environment variables - see src/env_config.py for definitions)

# Lazy-load config on first access to ensure .env is loaded
_config_cache = None

def _get_env_config() -> dict:
    """Get environment configuration, loading it if necessary."""
    global _config_cache
    if _config_cache is None:
        _config_cache = get_config()
    return _config_cache

# Map of environment variable names to their config keys
_ENV_VAR_MAP = {
    "OPENROUTER_API_URL": "OPENROUTER_API_URL",
    "OPENROUTER_DEFAULT_MODEL": "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_TITLE_MODEL": "OPENROUTER_TITLE_MODEL",
    "VIDEO_CRF": "VIDEO_CRF",
}

def __getattr__(name: str):
    """Module-level __getattr__ for lazy loading of environment variables."""
    if name in _ENV_VAR_MAP:
        return _get_env_config()[_ENV_VAR_MAP[name]]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# These will be accessed via __getattr__ when imported
# They are not defined here to allow __getattr__ to handle them
__all__ = [
    "MAX_PAD_SEC",
    "PAD_INCREMENT_SEC",
    "BITRATE_FALLBACK_BPS",
    "AUDIO_BITRATE",
    "VIDEO_CRF",
    "OPENROUTER_API_URL",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_TITLE_MODEL",
    "TRANSCRIBE_PROMPT",
    "TITLE_PROMPT_TEMPLATE",
    "VIDEO_EXTENSIONS",
]

# --- AI Prompts ---

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = """\
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title—no commentary, no explanation, no quotes around it, and nothing else.

Rules: 60–90 characters (max 100). One title only. Be accurate and descriptive; prefer wording from the transcript.

Add the honorific ﷺ only when your generated title itself includes a mention of the Prophet (e.g. محمد، رسول الله، المصطفى، النبي). If the transcript mentions the Prophet but your title does not, do not add the honorific. Only add ﷺ immediately after each such mention that appears in the title you output.

Example: تعظيم الإمام مالك لسيدنا رسول الله ﷺ

Transcript:
{transcript}
"""

# --- File Type Constants ---

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}
