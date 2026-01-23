"""Configuration constants and environment variables for video processing."""

from src.env_config import get_config

# --- Trimming Constants ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"
PREFERRED_VIDEO_ENCODERS = [
    "h264_qsv",
    "h264_videotoolbox",
    "h264_amf",
]
VIDEO_CRF = 18

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
    "PREFERRED_VIDEO_ENCODERS",
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
Generate a YouTube video title in Arabic based on the Arabic transcript below.

═══════════════════════════════════════════════════════════════
HONORIFICS REQUIREMENT (CRITICAL - MUST FOLLOW):
═══════════════════════════════════════════════════════════════
If the transcript mentions Prophet Muhammad in ANY way, you MUST include 
the honorific ﷺ immediately after EVERY mention in the title.

This applies to ALL references including:
- محمد
- رسول الله
- المصطفى
- النبي
- سيدنا رسول الله
- سيدنا محمد
- النبي محمد
- رسول الله صلى الله عليه وسلم
- Any other reference to the Prophet

This is non-negotiable and must be followed in every single title.

═══════════════════════════════════════════════════════════════
REQUIREMENTS:
═══════════════════════════════════════════════════════════════
1. Maximum 100 characters (strict limit) - aim for 60-90 characters for better descriptiveness
2. Accurately reflect the main topic/content discussed in the transcript
3. Be descriptive and informative - include key details from the transcript
4. Use words from the transcript verbatim when possible
5. Title only - no quotes, no extra commentary, no explanations

═══════════════════════════════════════════════════════════════
FORMATTING RULES:
═══════════════════════════════════════════════════════════════
- Make the topic part descriptive enough to understand what is discussed
- Follow the honorific requirement above if Prophet Muhammad is mentioned

═══════════════════════════════════════════════════════════════
EXAMPLES:
═══════════════════════════════════════════════════════════════
- تعظيم الإمام مالك لسيدنا رسول الله ﷺ
- كتاب الشفاء بتعريف حقوق المصطفى ﷺ

═══════════════════════════════════════════════════════════════
Arabic transcript:
{transcript}

Generate ONE title only (60-90 characters recommended, max 100, accurately reflecting the Arabic transcript content):
"""

# --- File Type Constants ---

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}
