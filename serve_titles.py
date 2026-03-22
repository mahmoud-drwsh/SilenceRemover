#!/usr/bin/env python3
"""Standalone title editor server (no OpenRouter key required)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uvicorn import Config, Server

from src.app.title_editor_server import build_app, get_port, probe_existing_server
from src.startup.title_editor_layout import build_title_editor_layout


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse and edit per-video titles; clears completed markers when a title changes.",
    )
    parser.add_argument("input_dir", type=str, help="Directory containing source videos")
    args = parser.parse_args()
    layout = build_title_editor_layout(Path(args.input_dir))
    port = get_port()
    if probe_existing_server(port):
        print(f"Title editor already running at http://127.0.0.1:{port}/ (not starting another).")
        return
    app = build_app(layout)
    config = Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    print(f"Title editor: http://127.0.0.1:{port}/")
    server.run()


if __name__ == "__main__":
    main()
