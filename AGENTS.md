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

### Deploying Media Manager

For a `remote-js/` release: run `bun run typecheck` from `remote-js/`, run `git diff --check`, then commit only the intended files and push `main` to `origin`. Dokploy builds from the `remote-js/` context with `remote-js/Dockerfile`; trigger or observe that deployment in Dokploy when its Git integration does not deploy automatically. Confirm the deployed service at `/healthz` before reporting success. `remote-js/README.md` is the source of truth for Dokploy environment setup; keep its credentials out of Git and UI output.

## Condensed changelog

- **Architecture and data model**: `src/app/pipeline.py` is the client-owned orchestrator; reusable media/FFmpeg/LLM packages live under `src/` and `packages/`; `remote-js/` is the Bun/Hono Media Manager. Every original has a stable source ID, and canonical pipeline-final cards link their overlaid/no-overlay finals, designer revisions, original, and subtitle actions.
- **Review, subtitles, and media UI**: Arabic review audio is title-first with approve/reopen, role-scoped trash and bulk approval. Both final variants expose deterministic Arabic SRT sidecars and selectable `mov_text` tracks. Project media lists page 24 cards and prefetch the next page; focused designer views hide the navigation rail. The active visual refresh preserves those behaviors while adding a stronger dark, RTL-ready hierarchy to canonical video bundles and audio-review states.
- **Variants, storage, and overlays**: New derived uploads require an existing original `source_id`; explicit variant/review/visibility/publication fields drive virtual views with legacy fallback. Designer uploads are immutable revisions whose newest successful upload becomes active and inherits the pipeline final's approved title; all derived-video downloads use that canonical title. Admins manage one checksum-tracked PNG logo per project for overlaid rendering only; no-overlay finals stay logo-free.
- **Processing resilience**: Verified originals use renewable, fenced server-worker leases with title-review checkpoints. Standard/no-overlay/subtitle markers, checksum-pinned leased remux jobs, legacy SRT normalization, guarded original-root backfill rehearsals, and original-deletion staling preserve recovery and retry behavior.
- **Analysis and uploads**: Media Manager owns Arabic review analysis through separately authenticated project and worker adapters; snippets are transient and provider limits/errors are contained. Pipeline uploads use authenticated presigned sessions, designer multipart uploads use bounded chunks, and the vertical launcher uploads originals while horizontal work remains local except transient analysis.
- **Operations and validation**: Startup preserves legacy classification, migrates fractional durations safely, and leaves retired public-sharing records inert. Python/Bun suites plus isolated Docker Compose cover focused behavior; the opt-in production black-box harness is self-cleaning, redacts credentials, and requires explicit confirmation.
