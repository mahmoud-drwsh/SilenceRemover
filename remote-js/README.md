# Media Manager

Canonical Media Manager service for SilenceRemover. It exposes the pipeline/browser HTTP contract on top of [Bun](https://bun.sh) + [Hono](https://hono.dev), proxies requests to a Postgres database (metadata) and an S3-compatible object store (media bytes), and is packaged as a single Docker image for [Dokploy](https://dokploy.com).

The pipeline client at [`packages/sr_media_manager/`](../packages/sr_media_manager) and the bundled browser SPA talk to this service directly.

## Stack

- **Runtime**: Bun (native multipart, native fetch, native streams, no build step)
- **Framework**: Hono (small, fast, portable; runs natively on Bun)
- **Postgres**: [`postgres`](https://github.com/porsager/postgres) (porsager) - parameterized SQL with schema awareness
- **S3**: [`@aws-sdk/client-s3`](https://www.npmjs.com/package/@aws-sdk/client-s3) for object storage (`PutObject`, `GetObject` with `Range`, `HeadObject`, `DeleteObject`, `ListObjectsV2`, `HeadBucket`)
- **MIME sniffing**: [`file-type`](https://www.npmjs.com/package/file-type) (replacement for libmagic / `python-magic`)
- **Validation**: [`zod`](https://zod.dev) + [`@hono/zod-validator`](https://www.npmjs.com/package/@hono/zod-validator) (replacement for Pydantic)
- **ffprobe**: shelled out via `Bun.spawn` (ffmpeg installed in the Docker image)

## Local development

```bash
cp .env.example .env       # fill DATABASE_URL, TOKEN_ENCRYPTION_KEY, S3_*, etc.
bun install
bun run dev                # auto-reloads on file changes
```

The server listens on `http://localhost:8080` by default:

- Project SPA: `http://localhost:8080/projects/$MEDIA_TOKEN/test-project/`
- Admin dashboard: `http://localhost:8080/admin/$ADMIN_TOKEN/`

## Smoke Test

Run the focused local checks:

```bash
bun run typecheck
bun test
```

## Deploying to Dokploy

This service is a Docker container that listens on port `8080`. Dokploy / Traefik handle TLS termination upstream.

1. Push this repo to a Git remote that Dokploy can read.
2. Create a new **Application** in Dokploy and point it at this repo.
3. Set the build context to `remote-js/` (so Dokploy uses [`Dockerfile`](Dockerfile)).
4. Add the env vars from [`.env.example`](.env.example) under the Dokploy "Environment" tab.
5. Deploy. The container exposes `:8080`; Dokploy wires Traefik in front.

Alternatively, drop the [`docker-compose.yml`](docker-compose.yml) into Dokploy's "Compose" mode.

## Dokploy Postgres

The repo root `.env` can contain:

```bash
DOKPLOY_BASE=http://your-dokploy-host:3000
DOKPLOY_TOKEN=...
```

Create a Dokploy-managed Postgres database:

```bash
bun run provision:dokploy-postgres
```

If Dokploy has more than one project or environment, add `DOKPLOY_PROJECT_ID` and `DOKPLOY_ENVIRONMENT_ID` to the repo root `.env`. The command prints `DATABASE_URL`, `DB_SCHEMA`, and `TOKEN_ENCRYPTION_KEY` values for the Media Manager app.

## Schema Bootstrap

The service creates/updates the plain Postgres schema on startup. [`scripts/setup_postgres.sql`](scripts/setup_postgres.sql) is kept as the explicit SQL version for manual bootstrap or review.

Seed the first admin token with [`scripts/generate_admin_token.ts`](scripts/generate_admin_token.ts):

```bash
bun run generate-admin-token
```

The output includes a plaintext token and a SQL `INSERT` to apply to the Postgres database.

## Layout

```
remote-js/
├── package.json
├── tsconfig.json
├── Dockerfile
├── docker-compose.yml
├── src/                    # Backend service code
│   ├── index.ts            # Bun.serve entrypoint, startup checks
│   ├── config.ts           # env parsing
│   ├── db.ts               # postgres connection + schema-prefixed helpers
│   ├── auth.ts             # token hashing, rate limiter
│   ├── audit.ts            # admin_audit_log inserts
│   ├── storage.ts          # S3 wrappers (head/put/get-range/delete/list)
│   ├── mime.ts             # MIME tables + file-type sniff
│   ├── range.ts            # HTTP Range header parser
│   ├── sanitize.ts         # filename / file-id sanitizers
│   ├── ffprobe.ts          # duration probe via Bun.spawn
│   ├── schemas.ts          # zod schemas
│   ├── security.ts         # security-headers middleware
│   ├── shareLinks.ts       # hashed public share-token creation and verification
│   └── routes/
│       ├── files.ts        # File list/upload/update/delete routes, including raw video PUT /content
│       ├── stream.ts       # GET /projects/:t/:p/stream/:id
│       ├── public.ts       # Public share-token ready-video list and read-only streams
│       ├── projectSpa.ts   # /static/*, /video-player, SPA fallback
│       └── admin.ts        # /admin/:admin_token/* dashboard + admin API
├── frontend/               # Browser SPA assets served by the backend
└── scripts/
    ├── setup_postgres.sql
    ├── provision_dokploy_postgres.ts
    └── generate_admin_token.ts
```

## API Guarantees

The pipeline client and SPA depend on these stable behaviors:

- HTTP paths, methods, query parameters, and body shapes
- Pipeline media bytes use only `POST /projects/:token/:project/api/uploads/initiate`, `POST .../api/uploads/:sessionId/complete`, and `POST .../api/uploads/:sessionId/abort`; Media Manager authorizes and verifies transfers but does not proxy them.
- Status codes (200/201/400/401/404/409/413/429)
- Upload lifecycle logs (`UPLOAD_START`, `UPLOAD_RECEIVED`, `UPLOAD_STORED`, `UPLOAD_COMMITTED`, `UPLOAD_FAILED`)
- Headers (`Accept-Ranges`, `Content-Range`, `Content-Disposition: inline; filename*=UTF-8''<...>`), plus the same `SECURITY_HEADERS` block
- `MAX_FILE_SIZE = 500 * 1024 * 1024` (500 MB upload cap)
- Audio tag set `{todo, ready, trash}` (strict); `all` is a virtual unfiltered view, not a stored tag
- Video tags freeform; `all` is a virtual unfiltered view, not a stored tag; same overwrite rules (audio = strict 409, video = different-title overwrite)
- Pre-flight `?check_id=...&check_title=...` envelope with `{exists, would_overwrite, existing_title, provided_title}`
- Token storage: SHA-256 hashes in `media_manager.auth_tokens`; recoverable media token encrypted with `TOKEN_ENCRYPTION_KEY`
- IP-based admin login rate limit (8 attempts / 15 minutes)
- Admin audit log writes to `media_manager.admin_audit_log`
- Public share links use dedicated hashed tokens and expose only non-trash, non-pending videos with `FB` or `TT` publication tags
