"""Shared OpenRouter SDK client with retry logic for transcribe and title modules."""

import random
import re
import sys
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
    """Write one request/response pair as separate timestamped files under log_dir/logs/.

    Files are named using the Unix timestamp (seconds) of the request:
    - <ts>_request.txt
    - <ts>_response.txt
    """
    ts_unix = int(time.time())
    logs_dir = log_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        request_path = logs_dir / f"{ts_unix}_request.txt"
        response_path = logs_dir / f"{ts_unix}_response.txt"
        request_body = (
            f"MODEL: {model}\n"
            f"TIMESTAMP_UNIX: {ts_unix}\n"
            f"INPUT:\n{input_text}\n"
        )
        response_body = (
            f"MODEL: {model}\n"
            f"TIMESTAMP_UNIX: {ts_unix}\n"
            f"OUTPUT:\n{output_text}\n"
        )
        request_path.write_text(request_body, encoding="utf-8")
        response_path.write_text(response_body, encoding="utf-8")
    except OSError:
        # Do not fail the request if logging fails
        pass


def _append_openrouter_error_log(
    log_dir: Path,
    model: str,
    input_text: str,
    *,
    attempt: int,
    error_kind: str,
    error_text: str,
    http_status: int | None = None,
    output_text: str | None = None,
) -> None:
    """Write one error record under log_dir/logs/errors/.

    This is best-effort and must never raise.
    """
    ts_unix = int(time.time())
    errors_dir = log_dir / "logs" / "errors"
    try:
        errors_dir.mkdir(parents=True, exist_ok=True)
        error_path = errors_dir / f"{ts_unix}_attempt{attempt}_{error_kind}.txt"
        body = (
            f"MODEL: {model}\n"
            f"TIMESTAMP_UNIX: {ts_unix}\n"
            f"ATTEMPT: {attempt}\n"
            f"HTTP_STATUS: {http_status}\n"
            f"ERROR_KIND: {error_kind}\n"
            f"ERROR:\n{error_text}\n"
            f"INPUT:\n{input_text}\n"
        )
        if output_text is not None:
            body += f"OUTPUT:\n{output_text}\n"
        error_path.write_text(body, encoding="utf-8")
    except OSError:
        pass


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
                # The SDK may return either a plain string or a list of
                # content blocks. Normalize to a single text string.
                if isinstance(content, list):
                    text_parts: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    content = "".join(text_parts)

                # Ensure we are working with a string and trim whitespace.
                if isinstance(content, str):
                    normalized = content.strip()
                else:
                    normalized = str(content).strip()

                # When the model returns an empty response, explicitly log the
                # input that produced it so it's easier to debug.
                if not normalized:
                    preview = input_log_text[:400] if input_log_text else "<no input captured>"
                    print(
                        f"OpenRouter returned empty response for model {model}. "
                        f"Input preview:\\n{preview}",
                        file=sys.stderr,
                    )
                    if log_dir:
                        _append_openrouter_log(log_dir, model, input_log_text, "[EMPTY RESPONSE]")
                        _append_openrouter_error_log(
                            log_dir,
                            model,
                            input_log_text,
                            attempt=attempt,
                            error_kind="empty_response",
                            error_text="Normalized response content was empty.",
                            http_status=None,
                            output_text="[EMPTY RESPONSE]",
                        )
                    return ""

                if log_dir:
                    _append_openrouter_log(log_dir, model, input_log_text, normalized)
                return normalized
            raise ValueError(f"Unexpected response format: {response}")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            last_err = e
            status = _status_code_from_error(e)
            if log_dir:
                _append_openrouter_error_log(
                    log_dir,
                    model,
                    input_log_text,
                    attempt=attempt,
                    error_kind="exception",
                    error_text=repr(e),
                    http_status=status,
                )
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
