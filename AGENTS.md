# Session change summaries for AI agents

Use [`CONTEXT.md`](CONTEXT.md) as the canonical glossary for media-processing terms such as original, derived video, overlaid video, no-overlay video, linked, backfill, and self-heal.

After code or config changes, agents append short notes here. When this file grows past ~20 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Agent Workflow Rules

- **ALWAYS use the `question` tool** when clarification is needed, when weighing tradeoffs, or when the user might have a preference. Do not ask questions inline in text responses—use the dedicated tool.
- **NEVER** hardcode the domain name in the code.

## Agent skills

### Issue tracker

GitHub Issues are the work tracker. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.

## Condensed changelog

- **Architecture and variants**: `src/app/pipeline.py` is the client-owned orchestrator; reusable media/FFmpeg/LLM modules live under `src/` and `packages/`; `remote-js/` is the Bun/Hono Media Manager. Each original has a stable source ID, with linked overlaid/no-overlay finals, designer uploads, originals, and subtitle actions on one canonical card.
- **Resilience and compatibility**: Legacy links/classification are preserved on startup and changed only by a guarded, report-first backfill rehearsal; independent standard/no-overlay/subtitle markers support retries and adoption. Subtitle backfill uses checksum-pinned, leased, atomic remux jobs, and legacy SRTs are normalized.
- **Subtitles and review**: Retained speech produces deterministic Arabic SRTs; both final variants embed selectable `mov_text` subtitles and expose a sidecar download. Audio review is title-only with approve/reopen, role-scoped trash/bulk approval, and `needs-designer` only shows finals without an active designer revision.
- **Server processing and uploads**: Verified originals default to fenced, renewable server-worker leases with checkpointed rendering after title approval. Pipeline uploads use authenticated presigned sessions; designer multipart parts proxy in bounded 8 MiB chunks. The vertical launcher uploads originals; the horizontal launcher remains local except for transient snippet analysis.
- **Project overlays**: Admins manage one checksum-tracked PNG logo per project; workers fetch it only for overlaid rendering. The client may seed its local logo once when the server has none; no-overlay finals stay logo-free.
- **Validation and skills**: Python and Bun test suites cover focused behavior, with Docker Compose for Postgres/MinIO. Repo-local copies of globally installed skills were removed; only the repository-specific Supabase skills remain locked.
- **Original-root safety audit**: The authenticated `original-rooted-rehearsal` route is report-only: it produces the guarded backfill fingerprint and distinct linked/projected/unresolved counts from the private service database, with no HTTP apply path. `docs/original-rooted-backfill-runbook.md` governs backup, validation, and guarded manual recovery.
- **Original-root rollout**: New derived uploads require an existing original `source_id`; explicit variant/review/visibility/publication fields drive canonical cards and virtual views while legacy tags remain intact. The rehearsal script defaults to dry-run and reports ambiguous legacy rows without writes.
- **Shared review analysis**: Media Manager owns Arabic OGG review transcript/title analysis through separate project-token and source-worker-token adapters. Snippets remain transient; provider timeouts/retries, safe errors, public rate/concurrency controls, and configuration live in `remote-js`.
- **Server review delegation**: The source worker submits only uncheckpointed review OGGs to Media Manager’s worker-authenticated review-analysis adapter, atomically checkpoints the returned transcript/title, and reuses completed review checkpoints on retries; subtitle generation remains worker-owned.
- **Duration migration**: Media Manager startup upgrades legacy integer `files.duration` columns to `double precision`, preserving fractional probe durations required when publishing server-rendered artifacts.
- **Manual production verification**: `scripts/black_box_source_processing.py` is an opt-in, self-cleaning source-processing black-box harness; it is deliberately excluded from CI and requires explicit production confirmation.
- **Harness validation**: The black-box lifecycle has injectable download, FFmpeg, client, and polling seams with deterministic fake-backed tests; production remains manual and cost-bounded.
