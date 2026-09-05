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

- **Architecture**: Local orchestration in `src/app/pipeline.py`; reusable media/FFmpeg/LLM modules in `src/` and `packages/`; Bun/Hono Media Manager in `remote-js/`. Stable original source IDs link both finals, designer revisions, originals and subtitles on one canonical card.
- **Natural target policy**: Fixed detection with bounded pause allocation (edited-gap floor 0.6s, cap 1.2s, exclusive target and 0.5s headroom). Infeasibility/errors propagate; final/upload durations are checked. See `docs/research/natural-pause-budget.md`; Arabic listening validation remains required. Non-target policy stays unchanged.
- **Resilience/migration**: Separate final/no-overlay/subtitle completion markers. Policy-versioned target scripts; target/policy-mismatched server checkpoints fail rather than reusing subtitles/approval on a new timeline. Completed outputs are not auto-migrated. Legacy classification is preserved; link backfill is guarded and report-first.
- **Subtitles/review**: Deterministic Arabic SRTs follow retained speech; both finals embed selectable mov_text tracks and expose sidecars. Backfill uses checksum-pinned leased atomic remux. Title-only audio approve/reopen, role-scoped trash/bulk approval, needs-designer excludes active designer revisions.
- **Server processing**: Renewable fenced worker leases and durable trim/render/review checkpoints. Media Manager owns transient OGG review analysis via separate project/worker adapters, provider retries/limits and safe errors. Worker owns subtitles. Vertical uploads originals; horizontal stays local except transient snippet analysis.
- **Uploads/overlays**: Authenticated presigned sessions; bounded 8 MiB designer proxy parts. One checksum-tracked PNG project logo, fetched only for overlaid output, with optional one-time local seeding. No-overlay stays logo-free. Startup upgrades integer duration to double precision.
- **Original safety**: Authenticated original-root rehearsal is report-only, with fingerprint and linked/projected/unresolved counts; no HTTP apply. Follow `docs/original-rooted-backfill-runbook.md`. Derived uploads require an existing original. Trashed-original deletion transactionally stales nonterminal jobs while completed/failed remain terminal.
- **Validation**: Python/Bun suites, isolated Postgres/MinIO Compose; only repo-specific Supabase skills locked. Production black-box harness is opt-in, excluded from CI, requires explicit production confirmation, and has credential-free fake-backed tests. Cleanup retries/stabilizes, redacts credentials/URLs and preserves original failure. Prior production acceptance verified review, subtitles, both finals, fractional durations and no leftover test files. Stored check_id rows omit exists; only missing rows return exists:false.
