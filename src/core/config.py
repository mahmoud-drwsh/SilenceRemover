"""Central configuration: environment variables (with validation).

Only secrets (e.g. OPENROUTER_API_KEY) need to live in .env; all other options have
defaults in src/core/constants.py and are configured via CLI flags or constants.
Use load_config() / get_config() for env-backed values at runtime.
"""

import os
from typing import Any

# --- Environment variable definitions (metadata, validation) ---

# We intentionally keep only secrets (API keys) in the environment. All other
# tuning knobs are configured via CLI flags or constants in src/core/constants.py.

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


__all__ = [
    "ENV_VARS",
    "load_config",
    "get_config",
    "reset_config",
]
