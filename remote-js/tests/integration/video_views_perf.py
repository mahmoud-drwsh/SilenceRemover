"""Time the video views of a large project (#51).

The flow seeds a project with SQL: 1000 no-overlay cards, 1000 review audio
rows and 100 designer revisions (designer_of_id = the no-overlay ID). Half of
the revised cards have an active designer revision pointer. Then it times the
first page (limit=24, offset=0) of each video view and prints the median.

Set VIEWS_PERF_MAX_MS to change the limit for the median of each view
(default 300). Set it to 0 to only print the times.
"""

import json
import os
import statistics
import subprocess
import time
import urllib.request


APP = "http://app:8080"
PROJECT = "perf-project"
BASE = f"{APP}/projects/test-token/{PROJECT}"
CARDS = 1000
REVISIONS = 100
RUNS = 7
MAX_MS = float(os.environ.get("VIEWS_PERF_MAX_MS", "300"))


def psql(statement):
    subprocess.run(
        ["psql", "-h", "postgres", "-U", "media_manager", "-d", "media_manager",
         "-v", "ON_ERROR_STOP=1", "-At", "-c", statement],
        check=True, capture_output=True, text=True,
    )


for _ in range(60):
    try:
        if urllib.request.urlopen(f"{APP}/healthz", timeout=5).status == 200:
            break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("Media Manager did not become healthy")

columns = ("id, project, type, title, tags, duration, file_size, mime_type, created_at, "
           "source_id, designer_of_id, active_designer_revision_id, media_variant, "
           "review_status, visibility, publication_status")
psql(f"""
INSERT INTO media_manager.files ({columns})
SELECT 'perf-' || lpad(i::text, 5, '0') || '-no-overlay', '{PROJECT}', 'video', 'Card ' || i,
       '[]'::jsonb, 60, 1000, 'video/mp4', now() - (i || ' minutes')::interval,
       'perf-' || lpad(i::text, 5, '0'), NULL, NULL, 'no-overlay', NULL, 'active',
       CASE WHEN i % 10 = 0 THEN 'pending' ELSE 'published' END
  FROM generate_series(1, {CARDS}) AS i;
INSERT INTO media_manager.files ({columns})
SELECT 'perf-' || lpad(i::text, 5, '0'), '{PROJECT}', 'audio', 'Card ' || i,
       '["ready"]'::jsonb, 60, 1000, 'audio/mp4', now() - (i || ' minutes')::interval,
       'perf-' || lpad(i::text, 5, '0'), NULL, NULL, NULL, 'approved', 'active', NULL
  FROM generate_series(1, {CARDS}) AS i;
INSERT INTO media_manager.files ({columns})
SELECT 'perf-' || lpad(i::text, 5, '0') || '-no-overlay-designer-r1', '{PROJECT}', 'video', 'Card ' || i,
       '[]'::jsonb, 60, 1000, 'video/mp4', now(),
       'perf-' || lpad(i::text, 5, '0'), 'perf-' || lpad(i::text, 5, '0') || '-no-overlay', NULL,
       'designer', NULL, 'active', 'published'
  FROM generate_series(1, {CARDS}, {CARDS // REVISIONS}) AS i;
UPDATE media_manager.files AS card
   SET active_designer_revision_id = revision.id
  FROM media_manager.files AS revision
 WHERE revision.project = '{PROJECT}' AND revision.designer_of_id = card.id
   AND card.project = '{PROJECT}' AND split_part(card.id, '-', 2)::int % 20 = 1;
ANALYZE media_manager.files;
""")

QUERIES = {
    "all": "view=all",
    "needs-designer": "view=needs-designer",
    "designer": "view=designer",
    "pending": "view=pending",
    "trash": "view=trash",
    "designer_missing": "designer_missing=true",
}

failed = []
counts = {}
for name, query in QUERIES.items():
    path = f"{BASE}/api/files?type=video&{query}&limit=24&offset=0"
    times = []
    for run in range(RUNS + 1):
        started = time.perf_counter()
        response = urllib.request.urlopen(path, timeout=120)
        body = json.load(response)
        elapsed = (time.perf_counter() - started) * 1000
        if run > 0:  # The first run warms the caches.
            times.append(elapsed)
    counts[name] = int(response.headers["X-Total-Count"])
    median = statistics.median(times)
    print(f"{name:17s} median {median:8.1f} ms  max {max(times):8.1f} ms  "
          f"total {counts[name]:5d}  page {len(body)}")
    if MAX_MS > 0 and median > MAX_MS:
        failed.append(name)

# The views filter the cards.
assert counts["all"] == CARDS, counts
assert counts["designer"] == REVISIONS, counts
assert counts["needs-designer"] == CARDS - REVISIONS, counts
assert counts["designer_missing"] == counts["needs-designer"], counts
assert counts["pending"] == CARDS // 10, counts
if failed:
    raise SystemExit(f"views slower than {MAX_MS} ms: {failed}")
print("isolated video views performance flow passed")
