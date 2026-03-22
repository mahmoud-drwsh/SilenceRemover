"""Localhost FastAPI UI to edit per-video titles and clear completed markers for re-encode."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from src.core.cli import collect_video_files
from src.core.paths import get_completed_path, get_title_path
from src.ffmpeg.probing import delete_final_videos_matching_source
from src.startup.title_editor_layout import TitleEditorLayout

SERVICE_ID = "silence-remover-title-editor"
DEFAULT_PORT = 8765
PROBE_TIMEOUT_SEC = 0.75


def get_port() -> int:
    return int(os.environ.get("TITLE_EDITOR_PORT", str(DEFAULT_PORT)))


def probe_existing_server(port: int) -> bool:
    """Return True if our title editor is already listening on port."""
    url = f"http://127.0.0.1:{port}/status"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SEC) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return False
    return bool(data.get("ok")) and data.get("service") == SERVICE_ID


def _read_title(temp_dir: Path, stem: str) -> str:
    p = get_title_path(temp_dir, stem)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _stem_to_video_map(layout: TitleEditorLayout) -> dict[str, Path]:
    return {p.stem: p for p in collect_video_files(layout.input_dir)}


def _render_page(layout: TitleEditorLayout) -> str:
    videos = collect_video_files(layout.input_dir)
    rows: list[str] = []
    for v in videos:
        stem = v.stem
        title = _read_title(layout.temp_dir, stem)
        safe_stem = escape(stem)
        safe_name = escape(v.name)
        safe_val_attr = escape(title, quote=True)
        rows.append(
            f"<tr><td>{safe_name}</td>"
            f'<td><input type="text" style="width:100%;min-width:240px" '
            f'data-stem="{safe_stem}" value="{safe_val_attr}" /></td></tr>'
        )
    body_rows = "\n".join(rows) if rows else "<tr><td colspan=2>(no videos)</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Title editor</title>
</head>
<body>
<h1>Edit titles</h1>
<p>
  <button type="button" onclick="location.reload()">Refresh</button>
  <a href="/status">/status</a>
  — Input: <code>{escape(str(layout.input_dir))}</code>
</p>
<table border="1" cellpadding="6" cellspacing="0">
<thead><tr><th>Video</th><th>Title</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
<p><button type="button" id="saveBtn">Save</button> <span id="msg"></span></p>
<script>
async function saveAll() {{
  const msg = document.getElementById("msg");
  msg.textContent = "";
  const inputs = document.querySelectorAll("input[data-stem]");
  const titles = {{}};
  inputs.forEach((el) => {{ titles[el.dataset.stem] = el.value; }});
  const res = await fetch("/save", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{ titles }}),
  }});
  const text = await res.text();
  if (!res.ok) {{
    msg.textContent = "Error: " + text;
    return;
  }}
  msg.textContent = "Saved.";
}}
document.getElementById("saveBtn").addEventListener("click", saveAll);
</script>
</body>
</html>"""


class _SaveBody(BaseModel):
    titles: dict[str, str] = Field(default_factory=dict)


def build_app(layout: TitleEditorLayout) -> FastAPI:
    app = FastAPI()

    @app.get("/status")
    def status() -> JSONResponse:
        return JSONResponse(
            {"ok": True, "service": SERVICE_ID},
        )

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_render_page(layout))

    @app.post("/save")
    def save(body: _SaveBody) -> JSONResponse:
        stem_to_video = _stem_to_video_map(layout)
        temp_dir = layout.temp_dir
        for stem, text in body.titles.items():
            if stem not in stem_to_video:
                raise HTTPException(status_code=400, detail=f"Unknown video stem: {stem}")
            new = text.strip()
            if not new:
                raise HTTPException(status_code=400, detail=f"Empty title for {stem}")
            title_path = get_title_path(temp_dir, stem)
            prev = title_path.read_text(encoding="utf-8").strip() if title_path.exists() else ""
            if new == prev:
                continue
            source_name = stem_to_video[stem].name
            delete_final_videos_matching_source(layout.output_dir, source_name)
            title_path.write_text(new, encoding="utf-8")
            get_completed_path(temp_dir, stem).unlink(missing_ok=True)
        return JSONResponse({"ok": True})

    return app
