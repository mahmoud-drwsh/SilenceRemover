#!/usr/bin/env python3
"""Backward-compatible entry; prefer: python main.py <input_dir> --title-editor"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.title_editor.standalone import run_title_editor_server


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Browse and edit per-video titles; clears completed markers when a title changes.",
    )
    parser.add_argument("input_dir", type=str, help="Directory containing source videos")
    args = parser.parse_args()
    run_title_editor_server(Path(args.input_dir))


if __name__ == "__main__":
    main()
