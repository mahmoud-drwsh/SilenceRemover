# Media Manager

The Media Manager service for SilenceRemover. It is one [Next.js](https://nextjs.org) app that runs on Node.js. It gives the HTTP contract for the pipeline client, the server worker, and the browser. It keeps metadata in Postgres and media bytes in an S3-compatible object store. It is one Docker image and one [Dokploy](https://dokploy.com) application.

The pipeline client in [`packages/sr_media_manager/`](../packages/sr_media_manager) and the server worker use this service. The API contract (routes, methods, bodies, status codes, headers, and auth) does not change between releases.

> This README tells about the service after the move into `remote-js/` (ticket #64 of spec #55). All paths in it are relative to the service folder.

## Stack

- **Runtime**: Node.js 24. Node runs the `.ts` files directly (type stripping), so `server.ts` and `scripts/*.ts` use only erasable TypeScript.
- **Framework**: Next.js (App Router, `output: "standalone"`). `server.ts` is a custom HTTP server. It runs the startup steps, then gives each request to Next.js.
- **UI**: React, Tailwind CSS, and shadcn/ui copies in `components/ui/`. The pages call only the public HTTP API from the browser.
- **Postgres**: [`postgres`](https://github.com/porsager/postgres) (porsager).
- **S3**: `@aws-sdk/client-s3` and `@aws-sdk/s3-request-presigner`.
- **MIME check**: `file-type`. **Validation**: `zod`. **Duration**: `ffprobe` (the image installs ffmpeg).
- **Packages**: Bun installs the packages from the frozen `bun.lock` only. `bunfig.toml` sets a 14-day minimum release age and exact versions. No package can run an install script.

## Local development

```bash
cp .env.example .env               # set DATABASE_URL, TOKEN_ENCRYPTION_KEY, S3_*, and the other values
bun install --frozen-lockfile
bun run build
node --env-file=.env server.ts     # production server on http://localhost:8080
```

`server.ts` makes and updates the database schema, re-queues the interrupted originals, checks the bucket, and removes the expired upload sessions. Then it starts to listen. It does not read `.env` itself; give the variables with `--env-file` or with the shell.

For UI work with hot reload, use `bun run dev` (`next dev` on port 8080). It does not run the startup steps, so start `server.ts` one time first (or apply [`scripts/setup_postgres.sql`](scripts/setup_postgres.sql)) to make the schema.

Pages:

- Project UI: `http://localhost:8080/projects/$MEDIA_TOKEN/<project>/`
- Admin dashboard: `http://localhost:8080/admin/$ADMIN_TOKEN/`
- Health check: `http://localhost:8080/healthz` returns `{"ok":true}`

## Tests

Run these commands from the service folder (`remote-js/`):

```bash
bun run typecheck      # tsc --noEmit
bun run test           # node --test: unit tests (src/**/*.test.ts)
bun run build          # next build
```

The two test seams run in the isolated Docker Compose stack. The stack uses a fresh database and synthetic media. It uses no production data, publishes no host port, and is removed after each flow. Run it from the repository root. Set `SRFRESH_TAG` to a unique value (for example the worktree name), so that parallel runs do not replace the images of each other. Run only one stack at a time on a small machine.

**Seam 1, the HTTP contract.** The black-box Python flows in [`tests/integration/`](tests/integration):

```bash
SRFRESH_TAG=<tag> remote-js/tests/integration/run_isolated_fresh.sh
# Runs: originals, canonical-card, source-processing, client-contract.

SRFRESH_TAG=<tag> remote-js/tests/integration/run_isolated_fresh.sh originals source-processing   # some flows
SRFRESH_TAG=<tag> remote-js/tests/integration/run_isolated_fresh.sh views-perf                     # by name only
```

**Seam 2, the browser.** The Playwright for Python tests in [`tests/browser/`](tests/browser):

```bash
SRFRESH_TAG=<tag> remote-js/tests/integration/run_isolated_fresh.sh browser
BROWSER_TESTS="test_video_views.PagingTest" SRFRESH_TAG=<tag> remote-js/tests/integration/run_isolated_fresh.sh browser
```

`BROWSER_TESTS` takes unittest names. Each test class extends `base.BrowserTestCase` (see `tests/browser/base.py`).

Set `ISOLATED_MINIO=dockerhub` to use the `minio/minio` images in place of the Chainguard MinIO override. After the runs, remove your images: `docker image ls 'srfresh-*'`, then `docker rmi` and `docker image prune -f`.

## Environment

The service uses the same variables as the previous service. [`.env.example`](.env.example) has each name and its default. Do not change the Dokploy environment for this release.

| Variable | Required | Default | Use |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | | Postgres connection URL. |
| `DB_SCHEMA` | no | `media_manager` | Postgres schema name. |
| `TOKEN_ENCRYPTION_KEY` | yes | | 32 random bytes, base64 or hex (`openssl rand -base64 32`). Encrypts the recoverable media token. |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | yes | | S3-compatible object store. |
| `PORT` | no | `8080` | HTTP port. |
| `SOURCE_PROCESSING_WORKER_TOKEN` | yes | | Token of the server worker for the `/internal/source-processing/` routes. |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` | for analysis | `https://openrouter.ai/api/v1` | Review and snippet analysis provider. |
| `OPENROUTER_TRANSCRIPTION_MODEL`, `OPENROUTER_TRANSCRIPTION_FALLBACK_MODEL`, `OPENROUTER_TITLE_MODEL`, `OPENROUTER_TITLE_FALLBACK_MODEL` | no | see `.env.example` | Models. A `chat:` prefix sends the audio to a chat model. |
| `REVIEW_ANALYSIS_*` | no | see `.env.example` | Timeout, attempts, deadline (keep it below the worker's 150 s wait), and the public rate limit and concurrency. |
| `SOURCE_PROCESSING_LEASE_SECONDS`, `SOURCE_PROCESSING_PROFILE` | no | `1800`, `v1` | Worker lease length and processing profile. |
| `SOURCE_PROCESSING_PROJECT`, `SOURCE_PROCESSING_ENCODER` | worker only | | The server worker reads these. The service does not. |

Keep the real values in Dokploy only. Do not put them in Git, in logs, or in UI output.

## Operator scripts

Run these from the service folder on a host with Node.js 22.18 or later (or in the running container, where the scripts are in `/app/scripts`; the image has no Bun, so use the `node` form there).

**Admin token.** Print a new admin token and the SQL that stores its SHA-256 hash:

```bash
bun run generate-admin-token          # or: node scripts/generate_admin_token.ts
```

The output is a `-- Admin token: mm_admin_...` line and an `insert ... on conflict (kind) do update` statement for `media_manager.auth_tokens`. Apply the SQL to the database. Keep the token secret.

**Dokploy Postgres.** Make a Dokploy-managed Postgres database for a new installation. Put these in the repository root `.env`:

```bash
DOKPLOY_BASE=http://your-dokploy-host:3000
DOKPLOY_TOKEN=...
```

```bash
bun run provision:dokploy-postgres    # or: node scripts/provision_dokploy_postgres.ts
```

If Dokploy has more than one project or environment, also set `DOKPLOY_PROJECT_ID` and `DOKPLOY_ENVIRONMENT_ID`. Other optional values: `DOKPLOY_POSTGRES_NAME`, `DOKPLOY_POSTGRES_DATABASE`, `DOKPLOY_POSTGRES_USER`, `DOKPLOY_POSTGRES_PASSWORD`, `DOKPLOY_POSTGRES_IMAGE`. The script writes `DATABASE_URL`, `DB_SCHEMA`, and `TOKEN_ENCRYPTION_KEY` to `remote-js/.dokploy-postgres.env` (mode 600, ignored by Git).

**Schema bootstrap.** The service makes and updates the schema at startup, so a deploy needs no manual database step. [`scripts/setup_postgres.sql`](scripts/setup_postgres.sql) is the same schema as explicit SQL, for a manual bootstrap or a review:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/setup_postgres.sql
```

When you change the startup schema in `src/server/db.ts`, change this file too. To check it, apply the file to one empty database and start the app on another, then compare `pg_dump --schema-only --schema=media_manager` of the two.

## Deploying to Dokploy

The Dokploy application is named `frontend`. It builds from GitHub, branch `main`, with the build path `remote-js` and the default `Dockerfile`. **Auto deploy is on: each push to `main` builds and deploys the service.** The server worker application also deploys on each push to `main` (it builds `remote-js/Dockerfile.worker` from the repository root).

The image listens on port `8080`. Dokploy and Traefik terminate TLS in front of it. The image has a `HEALTHCHECK` on `/healthz`.

1. Run `bun run typecheck` and `bun run build` from `remote-js/`, and `git diff --check`. Run the two test seams.
2. Write down the image that runs now, so that you can roll back (see [Rollback](#rollback)).
3. Confirm that production has zero non-expired active upload sessions. Wait if an upload is in progress:

   ```sql
   select count(*) from media_manager.upload_sessions
   where state = 'active' and expires_at > now();
   ```

4. Push to `main` (or start a deploy of `frontend` in Dokploy if the Git integration does not deploy).
5. Watch the deployment log in Dokploy until it is done.
6. Confirm `/healthz` returns `{"ok":true}`. Then open the project UI and the admin dashboard, and check that the pipeline client and the server worker can connect.

The environment variables are in the Dokploy "Environment" tab of `frontend`. A new installation copies the names from [`.env.example`](.env.example).

## Rollback

The database schema is the same for this service and the previous one, so a rollback needs no database step. Use the fastest method that you prepared.

**Before each deploy: keep the previous image.** Dokploy builds the image with the application's `appName` as the image name (see the "General" data of `frontend`, or `application.one` in the Dokploy API) and replaces it on each build. On the Dokploy host, before you push:

```bash
docker image ls <appName>                                  # find the current image
docker tag <appName>:latest <appName>:rollback-<old-commit>
```

The tag keeps the old image when Dokploy builds the new one, and `docker image prune` does not remove a tagged image.

**Method 1: start the previous image (fastest, about one minute).** Dokploy runs the application as a Docker Swarm service with the `appName` as its name. On the Dokploy host:

```bash
docker service ls --filter name=<appName>                  # confirm the service name
docker service update --image <appName>:rollback-<old-commit> <appName>
```

Then confirm `/healthz`. This is a temporary state: the next Dokploy deploy of `frontend` builds from Git again. Do method 2 next, so that Git agrees with production.

**Method 2: deploy the previous commit (no host access, one build).** Revert the release commit (or the merge) on `main` and push it. Auto deploy builds and deploys the previous code. Confirm `/healthz`.

```bash
git revert --no-edit <release-commit>       # use -m 1 for a merge commit
git push origin main
```

**Method 3: Dokploy rollback (optional).** Dokploy can keep each deployed image in a registry and roll back to it from the deployment list. This needs a rollback registry in the `frontend` settings. It is off now. If you turn it on before a deploy, you can roll back from the Dokploy UI.

After a rollback, check that production has zero non-expired active upload sessions before you deploy again.

## Layout

```
remote-js/
├── server.ts               # Entry: startup, then Next.js; graceful stop on SIGTERM
├── next.config.ts          # standalone output, security headers, strict trailing slash
├── app/                    # Route handlers (API) and pages (project UI, admin)
├── components/ui/          # shadcn/ui copies only (scripts/shadcn-copy.py)
├── lib/                    # cn() helper
├── src/server/             # Server modules: config, db, storage, auth, uploads, worker, analysis
├── src/client/             # Browser logic without UI (URL model, file list paging)
├── scripts/                # Operator scripts, setup_postgres.sql, test seed scripts
├── tests/integration/      # Seam 1: runner, Python flows, fixtures
├── tests/browser/          # Seam 2: Playwright for Python
├── Dockerfile              # Service image (Dokploy)
├── Dockerfile.worker       # Server worker image (built from the repository root)
└── docker-compose*.yml     # Local and isolated test stacks
```
