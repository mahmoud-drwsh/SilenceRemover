# Session change summaries for AI agents

Use [`CONTEXT.md`](CONTEXT.md) as the canonical glossary for media-processing terms such as original, derived video, overlaid video, no-overlay video, linked, backfill, and self-heal.

After code or config changes, agents append short notes here. When this file grows past ~20 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Agent Workflow Rules

- **ALWAYS use the `question` tool** when clarification is needed, when weighing tradeoffs, or when the user might have a preference. Do not ask questions inline in text responses—use the dedicated tool.
- **NEVER** hardcode the domain name in the code.

## Condensed changelog

- **Architecture**: `src/app/pipeline.py` remains the client-owned orchestrator; reusable media/FFmpeg/LLM modules live under `src/` and `packages/`. `remote-js/` is the Bun/Hono Media Manager with Postgres metadata and S3-compatible bytes.
- **Media variants**: Each original has a stable source ID. Overlaid and no-overlay silence-removed videos link to it; no-overlay uses its dedicated tag/folder. Designer videos are service uploads linked through `designer_of_id` and do not alter pipeline output.
- **Original linking**: Startup repairs legacy derived-to-original links and no-overlay classification. A later original retry self-heals a matching legacy derived row. Linked cards offer original downloads without an Originals view.
- **Pipeline resilience**: Independent standard/no-overlay/subtitle markers support adoption and retries; locked/completed inputs and existing links are precomputed and reported only as aggregate skips. Audio-less sources and VAAPI/QSV/x265 encoding selection are supported.
- **Review UI**: Audio review is a title-only queue with explicit approve/reopen; non-admin ordering is oldest-first. Trash and bulk approval are appropriately role-scoped. `needs-designer` is focused to pipeline finals with no active designer revision.
- **Upload transport**: Pipeline uploads use authenticated presigned sessions. Designer multipart parts proxy through Media Manager in bounded 8 MiB chunks, avoiding bucket CORS requirements.
- **Subtitles**: Deterministic Arabic SRT timing is generated from retained-speech segments; both final variants contain a selectable `mov_text` track and a sidecar `{source-id}-subtitles` download. Compatibility normalization repairs legacy cue formatting and bounds cue duration.
- **Subtitle backfill**: Checksum-pinned remux jobs lease, stage, verify, atomically promote, and preserve metadata/links; existing server SRTs suppress duplicate OpenRouter work.
- **Server processing**: `source_processing` is the default for every verified original, with dedicated worker authentication, fenced renewable leases, bounded retries, recovery, and admin status/retry APIs. The CPU-only worker verifies a signed original, checkpoints/reuses trim/transcript/title/SRT data, creates linked review audio and SRT, waits for title approval, then renders/uploads linked no-overlay and overlaid MP4s with embedded selectable subtitles before completing. When Media Manager is configured, the client performs only the original upload.
- **Project overlay logo**: Admins can upload or replace one PNG logo per project. The file is stored in R2 with checksum metadata; the server worker lease-fetches it only while rendering an overlaid final. When the server has no logo, the client seeds its local `logo/logo.png` once; it cannot replace an admin-managed logo. No-overlay videos remain logo-free.
- **Upload eligibility**: Only `Start-VerticalVideoProcessing.ps1` inherits `MEDIA_MANAGER_URL` and uploads Originals for server processing. The horizontal launcher explicitly keeps Media Manager disabled and runs only local trim, transcript/title generation, and one silence-removed output—no subtitles, overlays, companion output, or upload.
- **Validation**: Python behavior has focused tests; `remote-js` has Bun tests and an isolated Docker Compose environment using Postgres and MinIO.
