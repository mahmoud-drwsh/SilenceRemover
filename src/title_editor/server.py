"""Localhost FastAPI UI to edit per-video titles and clear completed markers for re-encode."""

from __future__ import annotations

import errno
import json
import os
import time
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


def _is_file_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        return exc.errno in (errno.EACCES, errno.EPERM)
    return False


def _write_title_file_with_retry(path: Path, text: str, *, max_attempts: int = 10) -> None:
    """Write title text; retry on Windows transient locks (antivirus, pipeline, other handles)."""
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return
        except OSError as e:
            last = e
            if not _is_file_lock_error(e):
                raise
            if attempt == max_attempts - 1:
                break
            time.sleep(0.05 * (2**min(attempt, 6)))
    raise HTTPException(
        status_code=503,
        detail=(
            f"Could not write {path.name} (file locked or permission denied). "
            "Stop the SilenceRemover pipeline if it is running, close any program "
            f"that has this file open, then retry. Path: {path}"
        ),
    ) from last


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
        safe_title_body = escape(title)
        rows.append(
            f'<tr><td class="col-video">{safe_name}</td>'
            f'<td class="col-title"><textarea data-stem="{safe_stem}" rows="2" '
            f'class="title-field" spellcheck="true">{safe_title_body}</textarea></td></tr>'
        )
    body_rows = "\n".join(rows) if rows else "<tr><td colspan=2>(no videos)</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Title editor</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ margin: 1rem; font-family: system-ui, sans-serif; }}
table.editor {{
  width: 100%;
  max-width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}}
table.editor th, table.editor td {{
  padding: 6px 8px;
  border: 1px solid #333;
  text-align: start;
  vertical-align: middle;
}}
table.editor .col-video {{
  white-space: nowrap;
  width: 22%;
  max-width: min(28rem, 38vw);
  overflow: hidden;
  text-overflow: ellipsis;
}}
table.editor .col-title {{
  width: auto;
  min-width: 0;
  vertical-align: top;
}}
table.editor .col-title textarea.title-field {{
  display: block;
  width: 100%;
  min-width: 0;
  min-height: 2.75rem;
  max-height: 14rem;
  padding: 4px 6px;
  font: inherit;
  line-height: 1.35;
  overflow-x: hidden;
  overflow-y: auto;
  overflow-wrap: anywhere;
  word-wrap: break-word;
  white-space: pre-wrap;
  resize: vertical;
}}
</style>
</head>
<body>
<h1>Edit titles</h1>
<p>
  <button type="button" onclick="location.reload()">Refresh</button>
  <a href="/status">/status</a>
  — Input: <code>{escape(str(layout.input_dir))}</code>
</p>
<table class="editor">
<thead><tr><th class="col-video">Video</th><th class="col-title">Title</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
<p><button type="button" id="saveBtn">Save</button> <span id="msg"></span></p>
<script>
async function saveAll() {{
  const msg = document.getElementById("msg");
  msg.textContent = "";
  const fields = document.querySelectorAll("textarea[data-stem]");
  const titles = {{}};
  fields.forEach((el) => {{ titles[el.dataset.stem] = el.value; }});
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
            _write_title_file_with_retry(title_path, new)
            get_completed_path(temp_dir, stem).unlink(missing_ok=True)
        return JSONResponse({"ok": True})

    return app
