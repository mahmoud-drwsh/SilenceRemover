"""Render sample title-overlay PNGs via sr_title_overlay (no FFmpeg).

Run from repo root:

    uv run python temp/render_title_overlay_examples.py

Writes PNGs and a local font cache under ./png_temp/ (gitignored).
"""

from __future__ import annotations

from pathlib import Path

from src.core.constants import TITLE_BANNER_HEIGHT_FRACTION, TITLE_FONT_DEFAULT
from sr_title_overlay import build_title_overlay

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT = _REPO_ROOT / "png_temp"
_FONTS = _OUT / "fonts"

# Vertical 1080×1920-style frame (common short-form crop)
_VIDEO_W = 1080
_VIDEO_H = 1920
_BANNER_H = max(1, int(_VIDEO_H * TITLE_BANNER_HEIGHT_FRACTION))

_EXAMPLES: list[tuple[str, str]] = [
    ("example_short.png", "Hello"),
    (
        "example_long.png",
        "A fairly long English title that exercises shrinking and word wrap in the banner",
    ),
    ("example_ar.png", "السلام عليكم ورحمة الله"),
    ("example_mixed.png", "Mixed English and العربية in one title line"),
    # Enough words to exercise multi-line logic; keep count modest (layout is combinatorial in word count).
    ("example_twoline.png", "one two three four five six seven eight"),
]


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    _FONTS.mkdir(parents=True, exist_ok=True)
    for filename, title in _EXAMPLES:
        path = build_title_overlay(
            title=title,
            video_width=_VIDEO_W,
            banner_height=_BANNER_H,
            output_file=_OUT / filename,
            font_family=TITLE_FONT_DEFAULT,
            font_cache_dir=_FONTS,
        )
        print(path)
    print(f"Done. Banner {_VIDEO_W}×{_BANNER_H} (frame {_VIDEO_W}×{_VIDEO_H}).")


if __name__ == "__main__":
    main()
