"""Shared OpenRouter SDK client with retry logic for transcribe and title modules."""

import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openrouter import OpenRouter

OPENROUTER_LOG_FILENAME = "openrouter_requests.log"


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


def _messages_to_log_text(messages: list[dict]) -> str:
    """Extract readable input text from messages for logging (no raw base64)."""
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if content is None:
            continue
        if isinstance(content, str):
            parts.append(content)
            continue
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "input_audio":
                    inp = block.get("input_audio") or {}
                    data = inp.get("data", "")
                    fmt = inp.get("format", "?")
                    size = len(data) if isinstance(data, str) else 0
                    parts.append(f"[audio, format={fmt}, base64_length={size}]")
    return "\n".join(parts)


def _append_openrouter_log(log_dir: Path, model: str, input_text: str, output_text: str) -> None:
    """Append one request/response pair to the OpenRouter log file under log_dir."""
    log_file = log_dir / OPENROUTER_LOG_FILENAME
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    block = (
        f"---\n"
        f"[{ts}] REQUEST model={model}\n"
        f"INPUT:\n{input_text}\n"
        f"---\n"
        f"[{ts}] RESPONSE\n"
        f"OUTPUT:\n{output_text}\n"
        f"==========\n"
    )
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.open("a", encoding="utf-8").write(block)
    except OSError:
        pass  # do not fail the request if logging fails


def request(
    api_key: str,
    model: str,
    messages: list[dict],
    max_attempts: int = 5,
    initial_backoff_sec: float = 1.0,
    max_backoff_sec: float = 30.0,
    multiplier: float = 2.0,
    jitter_ratio: float = 0.2,
    log_dir: Optional[Path] = None,
) -> str:
    """Make OpenRouter API request with retry logic using the official SDK.

    Shared by transcribe and title modules. App attribution (http_referer, x_title)
    is set so usage appears as SilenceRemover in OpenRouter rankings/analytics.

    When log_dir is set, appends request/response input and output text to
    log_dir/openrouter_requests.log (sibling temp folder).

    Args:
        api_key: OpenRouter API key
        model: Model name to use
        messages: List of message dictionaries for the API
        max_attempts: Maximum number of retry attempts
        initial_backoff_sec: Initial backoff delay in seconds
        max_backoff_sec: Maximum backoff delay in seconds
        multiplier: Exponential backoff multiplier
        jitter_ratio: Jitter ratio for backoff
        log_dir: If set, append input/output text to log_dir/openrouter_requests.log

    Returns:
        Response text content
    """
    attempt = 0
    last_err: Exception | None = None
    suggested_delay = 6.0
    input_log_text = _messages_to_log_text(messages) if log_dir else ""

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
                content = response.choices[0].message.content or ""
                if log_dir:
                    _append_openrouter_log(log_dir, model, input_log_text, content)
                return content
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
