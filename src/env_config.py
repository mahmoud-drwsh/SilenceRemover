"""Deprecated: import from src.config instead.

This module re-exports for backward compatibility.
"""

from src.config import ENV_VARS, get_config, load_config, reset_config

__all__ = ["ENV_VARS", "load_config", "get_config", "reset_config"]
