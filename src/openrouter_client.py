"""Shared OpenRouter SDK client with retry logic for transcribe and title modules."""

import random
import re
import time

from openrouter import OpenRouter


def _parse_retry_seconds_from_error(err: Exception) -> float:
    """Parse retry delay from error message."""
    m = re.search(r"retry in\s+([0-9.]+)s", str(err), re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    m2 = re.search(r"retryDelay'?\s*:\s*'?(\d+)(s)?'?", str(err), re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            pass
    return 6.0


def _status_code_from_error(err: Exception) -> int | None:
    """Extract HTTP status code from SDK/httpx exception if present."""
    response = getattr(err, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    return None


def request(
    api_key: str,
    model: str,
    messages: list[dict],
    max_attempts: int = 5,
    initial_backoff_sec: float = 1.0,
    max_backoff_sec: float = 30.0,
    multiplier: float = 2.0,
    jitter_ratio: float = 0.2,
) -> str:
    """Make OpenRouter API request with retry logic using the official SDK.

    Shared by transcribe and title modules. App attribution (http_referer, x_title)
    is set so usage appears as SilenceRemover in OpenRouter rankings/analytics.

    Args:
        api_key: OpenRouter API key
        model: Model name to use
        messages: List of message dictionaries for the API
        max_attempts: Maximum number of retry attempts
        initial_backoff_sec: Initial backoff delay in seconds
        max_backoff_sec: Maximum backoff delay in seconds
        multiplier: Exponential backoff multiplier
        jitter_ratio: Jitter ratio for backoff

    Returns:
        Response text content
    """
    attempt = 0
    last_err: Exception | None = None
    suggested_delay = 6.0

    while attempt < max_attempts:
        try:
            with OpenRouter(
                api_key=api_key,
                http_referer="https://github.com/SilenceRemover",
                x_title="SilenceRemover",
            ) as client:
                response = client.chat.send(
                    model=model,
                    messages=messages,
                    stream=False,
                )
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                return content or ""
            raise ValueError(f"Unexpected response format: {response}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            last_err = e
            status = _status_code_from_error(e)
            if status is not None:
                if status == 429:
                    suggested_delay = _parse_retry_seconds_from_error(e)
                elif status >= 500:
                    suggested_delay = 5.0
                else:
                    # Client error (4xx other than 429) - don't retry
                    raise
            else:
                suggested_delay = _parse_retry_seconds_from_error(e)

        exp_delay = initial_backoff_sec * (multiplier ** attempt)
        base_delay = max(suggested_delay, exp_delay)
        delay = min(max_backoff_sec, base_delay)
        if jitter_ratio > 0:
            delay *= random.uniform(max(0.0, 1 - jitter_ratio), 1 + jitter_ratio)
        time.sleep(delay)
        attempt += 1

    raise last_err  # type: ignore[misc]
