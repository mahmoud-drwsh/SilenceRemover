"""Generate a PNG title overlay image for ffmpeg burn-in."""

from __future__ import annotations

import hashlib
import math
import re
import urllib.error
import urllib.request
from itertools import combinations
from pathlib import Path
from urllib.parse import quote_plus

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from sr_title_overlay.constants import (
    TITLE_BANNER_BG_ALPHA,
    TITLE_OVERLAY_MAX_LAYOUT_COMBINATIONS,
    TITLE_OVERLAY_MAX_LINES,
    TITLE_TWO_LINE_MIN_GAIN_PX,
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


def _text_pixel_width(draw: ImageDraw.ImageDraw, text: str, *, font: ImageFont.FreeTypeFont) -> float:
    """Ink width for layout; use instead of textlength so Arabic/RTL matches draw.textbbox."""
    bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    return float(bbox[2] - bbox[0])


def _stacked_text_block_height(
    draw: ImageDraw.ImageDraw,
    display_lines: list[str],
    *,
    font: ImageFont.FreeTypeFont,
    font_size: int,
) -> float:
    """Total vertical ink height when lines are stacked with the same gap as draw."""
    if not display_lines:
        return 0.0
    inter_line_gap = max(4, int(font_size * 0.1))
    total = 0.0
    for i, dl in enumerate(display_lines):
        bb = draw.textbbox((0, 0), dl, font=font, anchor="lt")
        total += float(bb[3] - bb[1])
        if i < len(display_lines) - 1:
            total += inter_line_gap
    return total


def _line_length_variance(logical_lines: list[str]) -> float:
    """Lower is more balanced line lengths (character counts)."""
    lens = [len(s) for s in logical_lines]
    if len(lens) < 2:
        return 0.0
    m = sum(lens) / len(lens)
    return sum((x - m) ** 2 for x in lens)


def _best_multi_line_layout(
    font_path: str,
    words: list[str],
    max_width: float,
    max_height: float,
    min_font_size: int = 1,
) -> tuple[list[str], int] | None:
    """Find the best word-boundary layout with 2..K lines, maximizing fitted font size."""
    n = len(words)
    if n < 2:
        return None

    best_lines: list[str] | None = None
    best_font_size = -1
    best_var = float("inf")
    best_k = 0

    max_k = min(TITLE_OVERLAY_MAX_LINES, n)
    for k in range(2, max_k + 1):
        num_layouts = math.comb(n - 1, k - 1)
        if num_layouts > TITLE_OVERLAY_MAX_LAYOUT_COMBINATIONS:
            continue

        for cuts in combinations(range(1, n), k - 1):
            boundaries = (0,) + cuts + (n,)
            logical = [" ".join(words[boundaries[i] : boundaries[i + 1]]) for i in range(k)]
            display_lines = [_line_for_pillow(line) for line in logical]

            hi_size = _estimate_font_size_upper_bound(
                font_path, display_lines, max_width, max_height
            )
            if hi_size < min_font_size:
                continue
            candidate_size = _largest_fitting_font_size(
                font_path,
                display_lines,
                max_width,
                max_height,
                lo=min_font_size,
                hi=hi_size,
            )
            if candidate_size < min_font_size:
                continue

            var = _line_length_variance(logical)
            if candidate_size > best_font_size:
                best_font_size = candidate_size
                best_var = var
                best_k = k
                best_lines = logical
            elif candidate_size == best_font_size:
                if var < best_var:
                    best_var = var
                    best_k = k
                    best_lines = logical
                elif var == best_var and k > best_k:
                    best_k = k
                    best_lines = logical

    if best_lines is None:
        return None
    return best_lines, best_font_size


def _lines_fit(
    font_path: str,
    display_lines: list[str],
    max_width: float,
    max_height: float,
    font_size: int,
) -> bool:
    """Check if rendered display lines fit within width and height bounds."""
    if font_size <= 0:
        return False
    font = ImageFont.truetype(font_path, font_size)
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    visual_h = _stacked_text_block_height(
        dummy_draw, display_lines, font=font, font_size=font_size
    )
    return (
        all(_text_pixel_width(dummy_draw, dl, font=font) <= max_width for dl in display_lines)
        and visual_h <= max_height
    )


def _estimate_font_size_upper_bound(
    font_path: str,
    display_lines: list[str],
    max_width: float,
    max_height: float,
) -> int:
    """Estimate a safe upper bound on font size.

    Measures the widest line at a reference size to derive a per-character width
    ratio, then computes the font size that fills max_width. For single-line text
    this is the binding constraint; for multi-line, binary search still checks
    height naturally. Height is not used in the estimate to avoid wrongly capping
    single-line narrow titles.
    """
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    ref_font = ImageFont.truetype(font_path, 100)

    widest_line = max(display_lines, key=lambda dl: _text_pixel_width(dummy_draw, dl, font=ref_font))
    ref_w = _text_pixel_width(dummy_draw, widest_line, font=ref_font)
    chars = len(widest_line)
    char_w_per_pt = ref_w / (chars * 100)
    size_by_width = max(20, int(max_width / char_w_per_pt / chars))

    return size_by_width


def _largest_fitting_font_size(
    font_path: str,
    display_lines: list[str],
    max_width: float,
    max_height: float,
    lo: int = 1,
    hi: int = 5000,
) -> int:
    """Binary-search for the largest font size that fits the text within max bounds.

    Returns 0 when no tested size fits (for callers to handle explicitly).
    """
    lo = max(1, lo)
    if hi < lo:
        return 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        fits = _lines_fit(font_path, display_lines, max_width, max_height, mid)
        if fits:
            lo = mid
        else:
            hi = mid - 1
    if not _lines_fit(font_path, display_lines, max_width, max_height, lo):
        return 0
    return lo


def build_title_overlay(
    *,
    title: str,
    video_width: int,
    banner_height: int,
    output_file: Path,
    font_family: str,
    font_cache_dir: Path,
) -> Path:
    """Render a banner PNG with the title centered inside.

    The PNG is sized exactly to the banner dimensions (video_width × banner_height).
    FFmpeg then overlays it at the correct vertical position on the video.
    """
    cleaned_title = " ".join(title.split())
    if not cleaned_title:
        raise ValueError("Cannot render empty title overlay.")

    if video_width <= 0 or banner_height <= 0:
        raise ValueError(f"Invalid banner dimensions: {video_width}x{banner_height}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    font_path = _resolve_google_font_path(font_family, font_cache_dir)

    bg_alpha = int(255 * TITLE_BANNER_BG_ALPHA)
    banner_center_y = banner_height / 2

    image = Image.new("RGBA", (video_width, banner_height), (0, 0, 0, bg_alpha))
    draw = ImageDraw.Draw(image)

    max_width = max(1.0, video_width * 0.95)
    max_height = banner_height * 0.95

    max_display = _line_for_pillow(cleaned_title)
    single_line_display = [max_display]

    hi_size = _estimate_font_size_upper_bound(
        str(font_path), single_line_display, max_width, max_height
    )
    font_size = _largest_fitting_font_size(
        str(font_path), single_line_display, max_width, max_height, hi=hi_size
    )
    if font_size < 1:
        return output_file

    words = cleaned_title.split()
    logical_lines: list[str] = []

    if len(words) >= 2:
        best_multi = _best_multi_line_layout(
            str(font_path),
            words,
            max_width,
            max_height,
            min_font_size=1,
        )
        if best_multi is not None:
            split_lines, split_font_size = best_multi
            if split_font_size >= font_size + TITLE_TWO_LINE_MIN_GAIN_PX:
                logical_lines = split_lines
                font_size = split_font_size

    if not logical_lines:
        line = ""
        font = ImageFont.truetype(font_path, font_size)
        for word in words:
            candidate = f"{line} {word}".strip()
            w = _text_pixel_width(draw, _line_for_pillow(candidate), font=font)
            if w <= max_width:
                line = candidate
            else:
                if line:
                    logical_lines.append(line)
                line = word
        if line:
            logical_lines.append(line)

    if not logical_lines:
        return output_file

    display_lines = [_line_for_pillow(l) for l in logical_lines]
    if not _lines_fit(str(font_path), display_lines, max_width, max_height, font_size):
        fallback_font_size = _largest_fitting_font_size(
            str(font_path), display_lines, max_width, max_height, lo=1, hi=font_size
        )
        if fallback_font_size == 0:
            return output_file
        font_size = fallback_font_size
        display_lines = [_line_for_pillow(l) for l in logical_lines]

    font = ImageFont.truetype(font_path, font_size)
    inter_line_gap = max(4, int(font_size * 0.1))
    visual_block_h = _stacked_text_block_height(draw, display_lines, font=font, font_size=font_size)
    y_cursor = banner_center_y - visual_block_h / 2

    for i, (line, dl) in enumerate(zip(logical_lines, display_lines)):
        bb = draw.textbbox((0, 0), dl, font=font, anchor="lt")
        ink_w = bb[2] - bb[0]
        x = int((video_width - ink_w) / 2 - bb[0])
        draw.text((x, y_cursor), dl, fill=(255, 255, 255, 255), font=font, anchor="lt")
        line_h = bb[3] - bb[1]
        y_cursor += line_h
        if i < len(logical_lines) - 1:
            y_cursor += inter_line_gap

    image.save(output_file, format="PNG")
    return output_file
