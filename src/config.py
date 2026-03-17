"""Central configuration: environment variables (with validation) and static constants.

Only secrets (e.g. OPENROUTER_API_KEY) need to live in .env; all other options have
defaults here and can be overridden via environment variables. Use load_config() /
get_config() for env-backed values at runtime; static constants are available as
module attributes.
"""

import os
from typing import Any

# --- Environment variable definitions (metadata, validation) ---

# We intentionally keep only secrets (API keys) in the environment. All other
# tuning knobs are configured via CLI flags or module-level constants.

ENV_VARS = {
    "OPENROUTER_API_KEY": {
        "required": True,
        "type": str,
        "default": None,
        "description": "OpenRouter API key for transcription and title generation",
    },
}

# Cached config (loaded once)
_config: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    """Load and validate environment-backed configuration.

    Currently only OPENROUTER_API_KEY is read from the environment; all other
    options are configured via CLI flags or constants in this module.
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
            value = env_value
            if not isinstance(value, var_def["type"]):
                errors.append(
                    f"{var_name} must be of type {var_def['type'].__name__}, "
                    f"got {type(value).__name__}"
                )
            else:
                config[var_name] = value

    if errors:
        error_msg = "Configuration validation failed:\n  " + "\n  ".join(errors)
        raise ValueError(error_msg)

    return config


def get_config() -> dict[str, Any]:
    """Get cached configuration, loading it if necessary."""
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

# Default silence-detection parameters for non-target runs (can be overridden
# via CLI flags; see src/cli.py and main.py).
DEFAULT_NOISE_THRESHOLD = -50.0
DEFAULT_MIN_DURATION = 0.5
DEFAULT_PAD_SEC = 0.5

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

__all__ = [
    "ENV_VARS",
    "load_config",
    "get_config",
    "reset_config",
    "MAX_PAD_SEC",
    "PAD_INCREMENT_SEC",
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
]
