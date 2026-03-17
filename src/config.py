"""Central configuration: environment variables (with validation) and static constants.

Only secrets (e.g. OPENROUTER_API_KEY) need to live in .env; all other options have
defaults here and can be overridden via environment variables. Use load_config() /
get_config() for env-backed values at runtime; static constants are available as
module attributes.
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
    "OPENROUTER_DEFAULT_MODEL": {
        "required": False,
        "type": str,
        "default": "google/gemini-2.5-flash-lite:nitro",
        "description": "Model for audio transcription (must support audio input)",
    },
    "OPENROUTER_TITLE_MODEL": {
        "required": False,
        "type": str,
        "default": "google/gemini-2.5-flash-lite:nitro",
        "description": "Model for title generation (text-only)",
    },
    "NOISE_THRESHOLD": {
        "required": False,
        "type": float,
        "default": -50.0,
        "description": "Noise threshold in dB for silence detection (lower = more sensitive)",
        "validator": lambda x: x < 0,
        "error_msg": "NOISE_THRESHOLD must be negative (e.g., -50.0)",
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

# When --target-length is set: single detection, padding-only tuning
SIMPLE_DB = -55.0
SIMPLE_MIN_DURATION = 0.01

# When --target-length is set: multi-pass threshold sweep with padding-only tuning.
# Start from a conservative threshold (keep more silence), then increase aggressiveness
# only until the target can be met without exceeding it.
TARGET_MIN_DURATION = 0.01
TARGET_NOISE_THRESHOLDS_DB: list[float] = [-60.0, -55.0, -50.0, -45.0, -40.0, -35.0, -30.0, -25.0, -20.0]

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".m2ts",
}

# Subdirectory names in temp/
SNIPPET_DIR = "snippet"
TRANSCRIPT_DIR = "transcript"
TITLE_DIR = "title"
COMPLETED_DIR = "completed"
SCRIPTS_DIR = "scripts"

# Lazy env-backed attributes (used by __getattr__)
_ENV_ATTR_NAMES = frozenset({
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
    "SIMPLE_DB",
    "SIMPLE_MIN_DURATION",
    "TARGET_MIN_DURATION",
    "TARGET_NOISE_THRESHOLDS_DB",
    "VIDEO_CRF",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_TITLE_MODEL",
    "VIDEO_EXTENSIONS",
    "SNIPPET_DIR",
    "TRANSCRIPT_DIR",
    "TITLE_DIR",
    "COMPLETED_DIR",
    "SCRIPTS_DIR",
]
