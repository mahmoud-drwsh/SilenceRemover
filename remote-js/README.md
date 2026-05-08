# Media Manager

Canonical Media Manager service for SilenceRemover. It exposes the pipeline/browser HTTP contract on top of [Bun](https://bun.sh) + [Hono](https://hono.dev), proxies requests to a Supabase Postgres database (metadata) and an S3-compatible object store (media bytes), and is packaged as a single Docker image for [Dokploy](https://dokploy.com).

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
cp .env.example .env       # fill SUPABASE_DATABASE_URL, S3_*, etc.
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

## Schema bootstrap

Run [`scripts/setup_supabase_admin_auth.sql`](scripts/setup_supabase_admin_auth.sql) once to create the Supabase schema (`media_manager.files`, `media_manager.auth_tokens`, `media_manager.admin_audit_log`, plus the `vault_secret_id` column), then seed the first admin token with [`scripts/generate_admin_token.ts`](scripts/generate_admin_token.ts):

```bash
bun run generate-admin-token
```

The output is the same as the Python `generate_admin_token_sql.py` script: a plaintext token (used once) and a SQL `INSERT` to apply in Supabase.

## Layout

```
remote-js/
├── package.json
├── tsconfig.json
├── Dockerfile
├── docker-compose.yml
├── src/
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
│   └── routes/
│       ├── files.ts        # File list/upload/update/delete routes, including raw video PUT /content
│       ├── stream.ts       # GET /projects/:t/:p/stream/:id
│       ├── projectSpa.ts   # /static/*, /video-player, SPA fallback
│       └── admin.ts        # /admin/:admin_token/* dashboard + admin API
├── static/                 # Browser SPA assets
└── scripts/
    ├── setup_supabase_admin_auth.sql
    └── generate_admin_token.ts
```

## API Guarantees

The pipeline client and SPA depend on these stable behaviors:

- HTTP paths, methods, query parameters, and body shapes
- Raw video uploads via `PUT /projects/:token/:project/api/files/:id/content` with required `Content-Length`
- Status codes (200/201/400/401/404/409/413/429)
- Upload lifecycle logs (`UPLOAD_START`, `UPLOAD_RECEIVED`, `UPLOAD_STORED`, `UPLOAD_COMMITTED`, `UPLOAD_FAILED`)
- Headers (`Accept-Ranges`, `Content-Range`, `Content-Disposition: inline; filename*=UTF-8''<...>`), plus the same `SECURITY_HEADERS` block
- `MAX_FILE_SIZE = 500 * 1024 * 1024` (500 MB upload cap)
- Audio tag set `{todo, ready, all, trash}` (strict)
- Video tags freeform; same overwrite rules (audio = strict 409, video = different-title overwrite)
- Pre-flight `?check_id=...&check_title=...` envelope with `{exists, would_overwrite, existing_title, provided_title}`
- Token storage: SHA-256 hashes in `media_manager.auth_tokens`; recoverable plaintext for the media token in Supabase Vault
- IP-based admin login rate limit (8 attempts / 15 minutes)
- Admin audit log writes to `media_manager.admin_audit_log`
