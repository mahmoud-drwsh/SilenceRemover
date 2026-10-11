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

`remote-js/` is the Next.js Media Manager. The Dokploy application `frontend` builds it from `main` with the build path `remote-js/` and `remote-js/Dockerfile`. **Dokploy deploys on each push to `main`**, and the worker application deploys too. For a release: run `bun install --frozen-lockfile`, `bun run typecheck`, `bun run test`, and `bun run build` from `remote-js/`; run `git diff --check`; run both test seams (`remote-js/tests/integration/run_isolated_fresh.sh`, then its `browser` flow). Commit only the intended files. Before the push to `main`, confirm production has zero non-expired `upload_sessions` in `active` state; wait if any upload is in progress. Keep the previous image for rollback (see the Rollback section of `remote-js/README.md`). After the deploy, confirm `/healthz` before you report success. `remote-js/README.md` is the source of truth for the Dokploy environment; keep its credentials out of Git and UI output.

## Condensed changelog

- **Architecture and data model**: `src/app/pipeline.py` is the client-owned orchestrator. Reusable media, FFmpeg, and LLM packages are in `src/` and `packages/`. `remote-js/` is the Next.js Media Manager (spec #55). Each original has a stable source ID and one derived video: the no-overlay video (`<source_id>-no-overlay`). The canonical card is that video and links its designer revisions and its original.
- **Removed output (spec #44)**: The system makes no overlaid video, title banner, project logo, SRT, selectable subtitle track, or remux job. The packages, CLI flags, client calls, and scripts for them are deleted. The worker image installs only httpx. Old no-overlay videos can still contain an embedded subtitle track; we do not change them.
- **Media Manager app (spec #55)**: One Next.js app on Node 24 (standalone output; Bun only installs packages from the frozen `bun.lock`). `server.ts` runs the startup steps, then serves Next with the old Bun rules from `src/server/http.ts`: no keep-alive, request, or socket timeout, and a 128 MiB body limit with the Bun 413 responses before any route. `compress: false`; HTML pages get no Next Cache-Control. Server modules are in `remote-js/src/server/` (relative `.ts` imports, erasable syntax only, process-wide state on `globalThis`). Route handlers use `route()` and export `notFoundRoute` for the other methods. The API contract, environment names, database schema, and security headers are the same as in the old Bun/Hono service. `server.ts` takes the client IP from the rightmost X-Forwarded-For entry of an internal peer (Traefik), else from the socket peer. Port 8080 must be reachable only from Traefik (`docker-compose.yml` publishes it on 127.0.0.1 only). On SIGTERM, `server.ts` drains the requests in progress for up to `SHUTDOWN_GRACE_MS` (25 s), then closes the database pool.
- **UI**: Pages use only shadcn/ui copies (`remote-js/scripts/shadcn-copy.py` writes `components/ui/`), the stock Vidstack player, and plain fetch. Pages call only the public API from the browser. No other front end stays in the repository (#64).
- **Review and media UI**: Arabic review audio is title-first with approve/reopen, role-scoped trash, and bulk approval. Video views are All, Needs Designer, Designer Video, Pending, and Trash; removed view names open All. Project media lists page 24 cards and prefetch the next page.
- **Variants and designer revisions**: New derived uploads need an existing original `source_id`. Only the `no-overlay` and `designer` variants are accepted. Designer uploads are immutable revisions. The newest successful upload becomes active, and the active pointer is on the no-overlay row. A revision links to a card only by `designer_of_id` = the no-overlay ID. The card title and state come from the no-overlay row only. Downloads use the approved title.
- **Processing**: Vertical originals use renewable, fenced server-worker leases with title-review checkpoints. The worker encodes the no-overlay video before title approval and writes the approved title into its metadata. x265 uses CRF 22, the fast preset, the source frame rate, the `hvc1` tag, and faststart. Horizontal videos use the PC pipeline, which uploads no derived media.
- **Analysis and uploads**: Media Manager owns Arabic review analysis. Snippets are transient. Transcription uses `chat:google/gemini-3.5-flash-lite` with `elevenlabs/scribe-v2` as the fallback. Titles use `google/gemma-4-31b-it` with `google/gemini-3.8-flash` as the fallback. One analysis has a 110 s limit, and the worker waits 150 s. Pipeline uploads use authenticated presigned sessions. Designer uploads send bounded parts through the proxy part route.
- **Tests**: Unit tests run with `bun run test` (node:test). Seam 1 is the Python HTTP flows in `remote-js/tests/integration/`. Seam 2 is the Playwright for Python tests in `remote-js/tests/browser/` (the `browser` flow). Both seams run in the isolated Docker Compose stack; `SRFRESH_TAG` names the test images.
- **Operations**: The no-overlay data move is done. Its command, test flow, and runbook are deleted (#64), together with the video tag state migration and the backfill rehearsal. The operator scripts (`generate-admin-token`, `provision:dokploy-postgres`) and `setup_postgres.sql` are in `remote-js/scripts/`. The opt-in production black-box harness cleans up, redacts credentials, and needs explicit confirmation.
