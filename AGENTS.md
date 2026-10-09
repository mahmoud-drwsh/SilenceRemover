# Session change summaries for AI agents

Use [`CONTEXT.md`](CONTEXT.md) as the canonical glossary for media-processing terms such as original, derived video, no-overlay video, designer revision, linked, backfill, and self-heal.

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

For a `remote-js/` release: run `bun run typecheck` from `remote-js/`, run `git diff --check`, then commit only the intended files and push `main` to `origin`. Before triggering a deployment restart, confirm production has zero non-expired `upload_sessions` in `active` state; wait if any upload is in progress. Dokploy builds from the `remote-js/` context with `remote-js/Dockerfile`; trigger or observe that deployment in Dokploy when its Git integration does not deploy automatically. Confirm the deployed service at `/healthz` before reporting success. `remote-js/README.md` is the source of truth for Dokploy environment setup; keep its credentials out of Git and UI output.

## Condensed changelog

- **Architecture and data model**: `src/app/pipeline.py` is the client-owned orchestrator. Reusable media, FFmpeg, and LLM packages are in `src/` and `packages/`. `remote-js/` is the Bun/Hono Media Manager. Each original has a stable source ID. Since spec #44, each original has one derived video: the no-overlay video (`<source_id>-no-overlay`). The canonical card is that video and links its designer revisions and its original.
- **Removed output (spec #44)**: The system makes no overlaid video, title banner, project logo, SRT, selectable subtitle track, or remux job. The `sr_subtitles` and `sr_title_overlay` packages, the overlay part of `sr_filter_graph`, the overlay CLI flags, the speech-to-text call, the subtitle and logo client calls, and the subtitle backfill and SRT normalize scripts are deleted. The project has no pillow, arabic-reshaper, or python-bidi dependency; the worker image installs only httpx. Old no-overlay videos can still contain an embedded subtitle track; we do not change them.
- **Review and media UI**: Arabic review audio is title-first with approve/reopen, role-scoped trash, and bulk approval. Title generation and title review stay. Video views are All, Needs Designer, Designer Video, Pending, and Trash; removed view names open All. Project media lists page 24 cards and prefetch the next page. Focused designer views hide the navigation rail.
- **Variants and designer revisions**: New derived uploads need an existing original `source_id`. Only the `no-overlay` and `designer` variants are accepted; `pipeline-final` and `subtitle` uploads are rejected. Designer uploads are immutable revisions. The newest successful upload becomes active, and the active pointer is on the no-overlay row. Downloads use the approved title. The data move is done, so the legacy designer-link fallback is removed (#51). A revision links to a card only by `designer_of_id` = the no-overlay ID (index `files (project, designer_of_id)`). The card title and state come from the no-overlay row only. The legacy title rule stays only in `remote-js/src/noOverlayDataMove.ts`.
- **Processing**: Vertical originals use renewable, fenced server-worker leases with title-review checkpoints. The worker encodes the no-overlay video before title approval, writes the approved title into its metadata, and needs no OpenRouter key. x265 uses CRF 22 with the fast preset. The final encode keeps the source frame rate (constant), tags HEVC as `hvc1`, and uses faststart, so the result plays in browsers with an HEVC decoder (FFmpeg 7 gave level 6.x and `hev1` before). Horizontal videos use the PC pipeline, which also makes only the no-overlay video and uploads no derived media.
- **Analysis and uploads**: Media Manager owns Arabic review analysis through separate project and worker adapters. Snippets are transient. Pipeline uploads use authenticated presigned sessions. Designer multipart uploads use bounded chunks.
- **Data move and operations**: The data-move command (`dry-run`, `apply`, `drop-schema`) removes legacy overlaid, SRT, logo, and remux data after the deploy and after operator approval. It copies the overlaid state to the card in both directions and locks each row before it deletes its objects; see `docs/no-overlay-data-move-runbook.md`. Startup does not drop or re-create the removed tables. Python/Bun suites plus isolated Docker Compose cover behavior. The opt-in production black-box harness cleans up, redacts credentials, and needs explicit confirmation.
