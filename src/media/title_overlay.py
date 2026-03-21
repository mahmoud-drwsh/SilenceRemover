"""Generate a PNG title overlay image for ffmpeg burn-in."""

from __future__ import annotations

import hashlib
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

    widest_line = max(display_lines, key=lambda dl: dummy_draw.textlength(dl, font=ref_font))
    ref_w = dummy_draw.textlength(widest_line, font=ref_font)
    chars = len(widest_line)
    char_w_per_pt = ref_w / (chars * 100)
    size_by_width = max(20, int(max_width / char_w_per_pt / chars))

    return size_by_width


def _largest_fitting_font_size(
    font_path: str,
    display_lines: list[str],
    max_width: float,
    max_height: float,
    lo: int = 20,
    hi: int = 5000,
) -> int:
    """Binary-search for the largest font size that fits the text within max bounds."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        font = ImageFont.truetype(font_path, mid)
        dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bboxes = [dummy_draw.textbbox((0, 0), dl, font=font) for dl in display_lines]
        inter_line_gap = max(4, int(mid * 0.1))
        visual_h = bboxes[-1][3] - bboxes[0][1] + inter_line_gap * max(0, len(display_lines) - 1)
        fits = (
            all(dummy_draw.textlength(dl, font=font) <= max_width for dl in display_lines)
            and visual_h <= max_height
        )
        if fits:
            lo = mid
        else:
            hi = mid - 1
    return lo


def build_title_overlay(
    *,
    title: str,
    video_width: int,
    banner_height: int,
    output_file: Path,
    font_family: str = TITLE_FONT_DEFAULT,
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

    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_display = _line_for_pillow(cleaned_title)
    display_lines = [max_display]

    hi_size = _estimate_font_size_upper_bound(
        str(font_path), display_lines, max_width, max_height
    )
    font_size = _largest_fitting_font_size(
        str(font_path), display_lines, max_width, max_height, hi=hi_size
    )
    if font_size < 20:
        font_size = 20

    words = cleaned_title.split()
    logical_lines: list[str] = []
    line = ""
    font = ImageFont.truetype(font_path, font_size)
    for word in words:
        candidate = f"{line} {word}".strip()
        w = draw.textlength(_line_for_pillow(candidate), font=font)
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

    font = ImageFont.truetype(font_path, font_size)
    display_lines = [_line_for_pillow(l) for l in logical_lines]
    bboxes = [draw.textbbox((0, 0), dl, font=font) for dl in display_lines]
    line_height = max(b[3] - b[1] for b in bboxes)
    inter_line_gap = max(4, int(font_size * 0.1))
    visual_block_h = bboxes[-1][3] - bboxes[0][1] + inter_line_gap * max(0, len(logical_lines) - 1)

    first_anchor_y = banner_center_y - visual_block_h / 2 - bboxes[0][1]

    for i, (line, dl) in enumerate(zip(logical_lines, display_lines)):
        lw = draw.textlength(dl, font=font)
        x = int((video_width - lw) / 2)
        anchor_y = first_anchor_y + i * (line_height + inter_line_gap) + (bboxes[i][1] - bboxes[0][1])
        draw.text((x, anchor_y), dl, fill=(255, 255, 255, 255), font=font)

    image.save(output_file, format="PNG")
    return output_file
