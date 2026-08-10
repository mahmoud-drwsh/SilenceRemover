from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "pwsh" / "Move-IgnoredRawVideos.py"
SPEC = importlib.util.spec_from_file_location("move_ignored_raw_videos", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
raw_preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = raw_preflight
SPEC.loader.exec_module(raw_preflight)


def test_raw_preflight_batches_completed_and_locked_skip_output(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    raw_dir = tmp_path / "Vertical" / "raw"
    raw_dir.mkdir(parents=True)
    for name in ("completed-a.mkv", "completed-b.mkv", "locked.mkv"):
        (raw_dir / name).write_bytes(b"video")

    completed_dir = tmp_path / "Vertical" / "output" / "temp" / "completed"
    completed_dir.mkdir(parents=True)
    (completed_dir / "completed-a.txt").write_text("done", encoding="utf-8")
    (completed_dir / "completed-b.txt").write_text("done", encoding="utf-8")
    monkeypatch.setattr(raw_preflight, "is_file_locked", lambda path: path.name == "locked.mkv")

    summary = raw_preflight.invoke_raw_preflight_scan(
        label="Vertical",
        raw_path=raw_dir,
        short_duration_seconds=30.0,
        silence_threshold_db=-40.0,
        silence_min_duration_seconds=1.0,
        dry_run=False,
    )

    output = capsys.readouterr().out
    assert output == (
        "\n=== Vertical raw preflight ===\n"
        "[Vertical] Skipped 3/3 (completed 2, locked 1)\n"
    )
    assert summary.completed_skipped == 2
    assert summary.locked == 1
