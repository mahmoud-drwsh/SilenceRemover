"""Run the title editor HTTP server only (no pipeline phases)."""

from __future__ import annotations

from pathlib import Path

from uvicorn import Config, Server

from src.startup.title_editor_layout import build_title_editor_layout
from src.title_editor.server import build_app, get_port, probe_existing_server


def run_title_editor_server(input_dir: Path) -> None:
    """Start uvicorn for the title editor UI, or exit if an instance is already running."""
    layout = build_title_editor_layout(input_dir)
    port = get_port()
    if probe_existing_server(port):
        print(f"Title editor already running at http://127.0.0.1:{port}/ (not starting another).")
        return
    app = build_app(layout)
    config = Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    print(f"Title editor: http://127.0.0.1:{port}/")
    server.run()
