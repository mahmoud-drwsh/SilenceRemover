"""Central configuration: environment variables (with validation) and static constants.

Single source of truth for all settings. Use load_config() / get_config() for env-backed
values at runtime; static constants are available as module attributes.
"""

import os
from typing import Any, Callable

# --- Environment variable definitions (metadata, validation) ---

ENV_VARS = {
    "OPENROUTER_API_KEY": {
        "required": True,
        "type": str,
        "default": None,
        "description": "OpenRouter API key for transcription and title generation",
    },
    "OPENROUTER_API_URL": {
        "required": False,
        "type": str,
        "default": "https://openrouter.ai/api/v1/chat/completions",
        "description": "OpenRouter API endpoint URL",
    },
    "OPENROUTER_DEFAULT_MODEL": {
        "required": False,
        "type": str,
        "default": "google/gemini-2.0-flash-lite-001",
        "description": "Model for audio transcription (must support audio input)",
    },
    "OPENROUTER_TITLE_MODEL": {
        "required": False,
        "type": str,
        "default": "google/gemini-3-flash-preview",
        "description": "Model for title generation (text-only)",
    },
    "NOISE_THRESHOLD": {
        "required": False,
        "type": float,
        "default": -30.0,
        "description": "Noise threshold in dB for silence detection (lower = more sensitive)",
        "validator": lambda x: x < 0,
        "error_msg": "NOISE_THRESHOLD must be negative (e.g., -30.0)",
    },
    "MIN_DURATION": {
        "required": False,
        "type": float,
        "default": 0.5,
        "description": "Minimum duration of silence to be detected (seconds)",
        "validator": lambda x: x > 0,
        "error_msg": "MIN_DURATION must be positive",
    },
    "PAD": {
        "required": False,
        "type": float,
        "default": 0.5,
        "description": "Padding retained around detected silences (seconds)",
        "validator": lambda x: x >= 0,
        "error_msg": "PAD must be non-negative",
    },
    "SILENCE_REMOVER_WAIT_TIMEOUT_SEC": {
        "required": False,
        "type": float,
        "default": 30.0,
        "description": "Timeout for file operations (seconds)",
        "validator": lambda x: x > 0,
        "error_msg": "SILENCE_REMOVER_WAIT_TIMEOUT_SEC must be positive",
    },
    "SILENCE_REMOVER_WAIT_SLEEP_SEC": {
        "required": False,
        "type": float,
        "default": 0.25,
        "description": "Sleep interval between file operation retries (seconds)",
        "validator": lambda x: x > 0,
        "error_msg": "SILENCE_REMOVER_WAIT_SLEEP_SEC must be positive",
    },
    "VIDEO_CRF": {
        "required": False,
        "type": int,
        "default": 23,
        "description": "Video encoding quality (CRF: 0=lossless, 18=near-lossless, 23=default, 28=smaller files)",
        "validator": lambda x: 0 <= x <= 51,
        "error_msg": "VIDEO_CRF must be between 0 and 51",
    },
}

# Cached config (loaded once)
_config: dict[str, Any] | None = None


def _convert_type(value: str, target_type: type) -> Any:
    """Convert string value to target type."""
    if target_type == str:
        return value
    elif target_type == float:
        try:
            return float(value)
        except ValueError as e:
            raise ValueError(f"Invalid float value: {value}") from e
    elif target_type == int:
        try:
            return int(value)
        except ValueError as e:
            raise ValueError(f"Invalid int value: {value}") from e
    else:
        raise ValueError(f"Unsupported type: {target_type}")


def _validate_value(var_name: str, value: Any, var_def: dict[str, Any]) -> None:
    """Validate a single environment variable value."""
    expected_type = var_def["type"]
    if not isinstance(value, expected_type):
        raise ValueError(
            f"{var_name} must be of type {expected_type.__name__}, got {type(value).__name__}"
        )
    if "validator" in var_def:
        validator: Callable[[Any], bool] = var_def["validator"]
        if not validator(value):
            error_msg = var_def.get("error_msg", f"{var_name} validation failed")
            raise ValueError(error_msg)


def load_config() -> dict[str, Any]:
    """Load and validate all environment variables.

    Returns:
        Dictionary mapping environment variable names to their typed values.

    Raises:
        ValueError: If any required variable is missing or validation fails.
    """
    config: dict[str, Any] = {}
    errors: list[str] = []

    for var_name, var_def in ENV_VARS.items():
        env_value = os.environ.get(var_name)

        if var_def["required"]:
            if env_value is None or env_value.strip() == "":
                errors.append(f"{var_name} is required but not set")
                continue

        if env_value is not None:
            try:
                value = _convert_type(env_value, var_def["type"])
                _validate_value(var_name, value, var_def)
                config[var_name] = value
            except ValueError as e:
                errors.append(f"{var_name}: {e}")
        else:
            default = var_def["default"]
            if default is not None:
                config[var_name] = default
            elif not var_def["required"]:
                continue

    if errors:
        error_msg = "Configuration validation failed:\n  " + "\n  ".join(errors)
        raise ValueError(error_msg)

    return config


def get_config() -> dict[str, Any]:
    """Get cached configuration, loading it if necessary.

    Returns:
        Dictionary mapping environment variable names to their typed values.

    Raises:
        ValueError: If configuration loading fails.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset cached configuration (useful for testing)."""
    global _config
    _config = None


# --- Static constants (not from environment) ---

MAX_PAD_SEC = 10.0
PAD_INCREMENT_SEC = 0.01
BITRATE_FALLBACK_BPS = 3_000_000
AUDIO_BITRATE = "192k"

TRANSCRIBE_PROMPT = """Transcribe the Arabic audio as clean verbatim text in Arabic.
- No timestamps
- No speaker labels
- Keep punctuation and natural phrasing."""

TITLE_PROMPT_TEMPLATE = """\
Generate one YouTube video title in Arabic from the transcript below. The title must be in Arabic. Output only the title—no commentary, no explanation, no quotes around it, and nothing else.

Rules: 60–90 characters (max 100). One title only. Be accurate and descriptive; prefer wording from the transcript.

When your title includes the name محمد, always write سيدنا immediately before محمد. Add سيدنا only before محمد—not before other references (e.g. رسول الله، المصطفى، النبي).

Add the honorific ﷺ only when your generated title itself includes a mention of the Prophet (e.g. محمد، رسول الله، المصطفى، النبي). If the transcript mentions the Prophet but your title does not, do not add the honorific. Only add ﷺ immediately after each such mention that appears in the title you output.

Example: تعظيم الإمام مالك لسيدنا محمد ﷺ

Transcript:
{transcript}
"""

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}

# Lazy env-backed attributes (used by __getattr__)
_ENV_ATTR_NAMES = frozenset({
    "OPENROUTER_API_URL",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_TITLE_MODEL",
    "VIDEO_CRF",
})


def __getattr__(name: str) -> Any:
    """Lazy-load env-backed config attributes on first access."""
    if name in _ENV_ATTR_NAMES:
        return get_config()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ENV_VARS",
    "load_config",
    "get_config",
    "reset_config",
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
