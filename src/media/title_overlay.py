"""Generate a PNG title overlay image for ffmpeg burn-in."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote_plus

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from src.core.constants import (
    TITLE_BANNER_BG_ALPHA,
    TITLE_BANNER_HEIGHT_FRACTION,
    TITLE_BANNER_START_FRACTION,
    TITLE_FONT_DEFAULT,
)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", name.strip().lower())


def _download_google_font_zip(font_name: str) -> bytes:
    encoded = quote_plus(font_name)
    url = f"https://fonts.googleapis.com/css2?family={encoded}:wght@400"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            css = response.read().decode("utf-8", errors="replace")
            truetype_match = re.search(
                r"url\(([^)]+)\)\s*format\('truetype'\)",
                css,
            )
            if truetype_match is None:
                fallback_match = re.search(r"url\(([^)]+)\)", css)
                if fallback_match is None:
                    raise RuntimeError("Could not find a font URL in Google Fonts CSS response.")
                font_url = fallback_match.group(1)
            else:
                font_url = truetype_match.group(1)
            font_url = font_url.strip().strip("\"'")

            font_request = urllib.request.Request(font_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(font_request, timeout=30) as font_response:
                font_bytes = font_response.read()

            return font_bytes
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download Google Font '{font_name}' from {url}: {exc}") from exc


def _extract_ttf(data: bytes, destination: Path) -> Path:
    if not data:
        raise RuntimeError("Downloaded font payload is empty.")

    if not data[:4] in {b"\x00\x01\x00\x00", b"OTTO", b"ttcf"}:
        raise RuntimeError("Downloaded font data is not a valid TrueType file.")

    try:
        with destination.open("wb") as target:
            target.write(data)
    except OSError as exc:
        raise RuntimeError(f"Failed writing font file '{destination}': {exc}") from exc

    return destination


def _resolve_google_font_path(font_name: str, font_cache_dir: Path) -> Path:
    font_cache_dir.mkdir(parents=True, exist_ok=True)
    family_key = _slugify(font_name)
    hash_key = hashlib.sha1(font_name.strip().lower().encode("utf-8")).hexdigest()[:12]
    font_path = font_cache_dir / f"{family_key}_{hash_key}.ttf"
    if font_path.exists() and font_path.stat().st_size > 0:
        return font_path

    try:
        package = _download_google_font_zip(font_name)
        return _extract_ttf(package, font_path)
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to resolve Google Font '{font_name}': {exc}") from exc


_ARABIC_RESHAPER = arabic_reshaper.ArabicReshaper(
    configuration={
        "delete_harakat": False,
        "support_ligatures": True,
        "RIAL SIGN": True,
    }
)


def _line_for_pillow(logical_line: str) -> str:
    """Join Arabic letters and reorder for left-to-right glyph drawing (Pillow has no HarfBuzz)."""
    reshaped = _ARABIC_RESHAPER.reshape(logical_line)
    return get_display(reshaped)


def _wrap_title_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    line_to_display: Callable[[str], str],
) -> list[str]:
    """Word-wrap using *logical* tokens but measure width on display strings."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        width = draw.textlength(line_to_display(candidate), font=font)
        if width <= max_width:
            line = candidate
            continue

        if line:
            lines.append(line)
        if draw.textlength(line_to_display(word), font=font) > max_width:
            if not line:
                lines.append(word)
                line = ""
            else:
                line = word
        else:
            line = word

    if line:
        lines.append(line)
    return lines


def build_title_overlay(
    *,
    title: str,
    width: int,
    height: int,
    output_file: Path,
    font_family: str = TITLE_FONT_DEFAULT,
    font_cache_dir: Path,
) -> Path:
    """Render a title overlay PNG sized to the source video."""
    cleaned_title = " ".join(title.split())
    if not cleaned_title:
        raise ValueError("Cannot render empty title overlay.")

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid video size for title overlay: {width}x{height}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    font_path = _resolve_google_font_path(font_family, font_cache_dir)

    band_top = int(height * TITLE_BANNER_START_FRACTION)
    band_height = max(1, int(height * TITLE_BANNER_HEIGHT_FRACTION))
    background_alpha = int(255 * TITLE_BANNER_BG_ALPHA)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        xy=(0, band_top, width, band_top + band_height),
        fill=(0, 0, 0, background_alpha),
    )

    font_size = max(12, int(height / 12))
    font = ImageFont.truetype(font_path, font_size)
    max_line_width = max(1, int(width * 0.92))

    lines = _wrap_title_lines(
        draw, cleaned_title, font, max_line_width, line_to_display=_line_for_pillow
    )
    while True:
        if not lines:
            break

        bboxes = [
            draw.textbbox((0, 0), _line_for_pillow(line), font=font) for line in lines
        ]
        text_width = max(bbox[2] - bbox[0] for bbox in bboxes)
        text_height = sum((bbox[3] - bbox[1]) for bbox in bboxes) + 8 * (len(lines) - 1)

        if text_width <= max_line_width and text_height <= band_height * 0.9:
            break

        proposed_size = font.size - 2
        if proposed_size < 20:
            break

        font = ImageFont.truetype(font_path, proposed_size)
        lines = _wrap_title_lines(
            draw, cleaned_title, font, max_line_width, line_to_display=_line_for_pillow
        )

    if not lines:
        return output_file

    bboxes = [draw.textbbox((0, 0), _line_for_pillow(line), font=font) for line in lines]
    text_width = max(bbox[2] - bbox[0] for bbox in bboxes)
    line_height = max((bbox[3] - bbox[1]) for bbox in bboxes)
    total_height = line_height * len(lines) + 8 * max(0, len(lines) - 1)
    start_y = band_top + max(0, (band_height - total_height) // 2)
    y = start_y

    for line in lines:
        display_line = _line_for_pillow(line)
        line_width = draw.textlength(display_line, font=font)
        x = max(0, int((width - line_width) / 2))
        draw.text((x, y), display_line, fill=(255, 255, 255, 255), font=font)
        y += line_height + 8

    image.save(output_file, format="PNG")
    return output_file
