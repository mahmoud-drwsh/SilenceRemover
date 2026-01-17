"""Centralized environment variable configuration with validation.

This module serves as the single source of truth for all environment variables.
All environment variable definitions, defaults, types, and validation rules are defined here.
"""

import os
from typing import Any, Callable

# Environment variable definitions with metadata
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
}

# Cached config (loaded once)
_config: dict[str, Any] | None = None


def _convert_type(value: str, target_type: type) -> Any:
    """Convert string value to target type.
    
    Args:
        value: String value from environment
        target_type: Target type (str, float, int)
        
    Returns:
        Converted value
        
    Raises:
        ValueError: If conversion fails
    """
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
    """Validate a single environment variable value.
    
    Args:
        var_name: Environment variable name
        value: Value to validate
        var_def: Variable definition from ENV_VARS
        
    Raises:
        ValueError: If validation fails
    """
    # Type validation
    expected_type = var_def["type"]
    if not isinstance(value, expected_type):
        raise ValueError(
            f"{var_name} must be of type {expected_type.__name__}, got {type(value).__name__}"
        )
    
    # Custom validator
    if "validator" in var_def:
        validator: Callable[[Any], bool] = var_def["validator"]
        if not validator(value):
            error_msg = var_def.get("error_msg", f"{var_name} validation failed")
            raise ValueError(error_msg)


def load_config() -> dict[str, Any]:
    """Load and validate all environment variables.
    
    Returns:
        Dictionary mapping environment variable names to their typed values
        
    Raises:
        ValueError: If any required variable is missing or validation fails
    """
    config: dict[str, Any] = {}
    errors: list[str] = []
    
    for var_name, var_def in ENV_VARS.items():
        env_value = os.environ.get(var_name)
        
        # Handle required variables
        if var_def["required"]:
            if env_value is None or env_value.strip() == "":
                errors.append(f"{var_name} is required but not set")
                continue
        
        # Use environment value or default
        if env_value is not None:
            try:
                # Convert to appropriate type
                value = _convert_type(env_value, var_def["type"])
                # Validate value
                _validate_value(var_name, value, var_def)
                config[var_name] = value
            except ValueError as e:
                errors.append(f"{var_name}: {e}")
        else:
            # Use default value
            default = var_def["default"]
            if default is not None:
                config[var_name] = default
            elif not var_def["required"]:
                # Optional variable with no default - skip it
                continue
    
    if errors:
        error_msg = "Configuration validation failed:\n  " + "\n  ".join(errors)
        raise ValueError(error_msg)
    
    return config


def get_config() -> dict[str, Any]:
    """Get cached configuration, loading it if necessary.
    
    Returns:
        Dictionary mapping environment variable names to their typed values
        
    Raises:
        ValueError: If configuration loading fails
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset cached configuration (useful for testing)."""
    global _config
    _config = None
