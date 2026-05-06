# Media Manager (Next.js)

Next.js 15 port of the Python FastAPI service in [`../remote/`](../remote/). Same URL layout, JSON shapes, Supabase Postgres schema (`media_manager.*`), S3 key layout, and bundled SPAs (`public/mm/*.html` copied from `remote/static/`).

**Do not run the Python and Next.js services against the same production metadata/storage unless you intend to — one active deployment per environment is recommended.**

## Features (parity with `remote/app.py`)

- Audio & video uploads, tag workflow, streaming with HTTP Range
- Token in path: `/projects/{token}/{project}/…`
- Admin dashboard: `/admin/{admin_token}/…`
- Supabase Vault for recoverable media token; hashed admin/media tokens in `auth_tokens`
- S3-compatible storage (`forcePathStyle`, SigV4)

## Local development

```bash
cd remote-next
cp .env.example .env
# Fill SUPABASE_DATABASE_URL, S3_*, etc.
npm install
npm run dev
```

- Default dev server: `http://localhost:8080` (see `package.json` `dev` script)
- Project UI: `http://localhost:8080/projects/$PROJECT_TOKEN/your-project/`
- Admin: `http://localhost:8080/admin/$ADMIN_TOKEN/`

## Production / Dokploy (Docker)

1. Create an application from this repo, **Dockerfile** context: `remote-next/` (repository root path as appropriate for Dokploy).
2. Set environment variables (same names as Python service):

| Variable | Description |
|----------|-------------|
| `SUPABASE_DATABASE_URL` | Postgres connection string |
| `SUPABASE_DB_SCHEMA` | Default `media_manager` |
| `S3_ENDPOINT_URL` | S3-compatible endpoint |
| `S3_BUCKET` | Bucket name |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Credentials |
| `S3_REGION` | Region (e.g. `eu2`) |

3. Expose container port **3000**. Configure Traefik / your reverse proxy for TLS and routing (replaces the old Caddy + systemd setup used by the Python app).
4. Health: `GET /api/healthz` — verifies Postgres tables and S3 `HeadBucket`. Docker `HEALTHCHECK` uses this endpoint.

### Resource notes

- **ffmpeg/ffprobe** are installed in the image for upload duration probing (same role as Python + ffprobe).
- Large uploads (up to **500 MB**) mirror the Python limit; ensure proxy/body limits on Traefik allow your max upload size.

## API (unchanged paths)

| Method | Path |
|--------|------|
| GET | `/projects/<token>/<project>/api/files?type=audio\|video&tags=...&sort=asc\|desc&check_id=...&check_title=...&include_trash&include_pending` |
| POST | `/projects/<token>/<project>/api/files` (multipart: `id`, `title`, `type`, `tags`, `file`) |
| PUT | `/projects/<token>/<project>/api/files/<id>?type=audio\|video` |
| DELETE | `/projects/<token>/<project>/api/files/<id>?type=audio\|video` |
| GET | `/projects/<token>/<project>/stream/<id>?type=audio\|video` |
| GET | `/projects/<token>/<project>/video-player` |
| GET | `/projects/<token>/<project>/static/<path>` (legacy assets under `public/mm/static/`) |
| GET | `/admin/<admin_token>/api/projects` |
| GET | `/admin/<admin_token>/api/projects/s3-storage` |
| POST | `/admin/<admin_token>/api/refresh-admin-token` |
| POST | `/admin/<admin_token>/api/refresh-token` (legacy alias) |
| POST | `/admin/<admin_token>/api/media-token` JSON `{ "token": "..." }` |
| * | `/admin/<admin_token>/files/...` → **404** `"Admin File Browser has been removed"` |
| GET | `/api/healthz` |

Admin token bootstrap and SQL helpers remain in [`../remote/scripts/`](../remote/scripts/) (e.g. `generate_admin_token_sql.py`, `setup_supabase_admin_auth.sql`).

## SilenceRemover integration

Set the same base URL style as the Python README:

```bash
MEDIA_MANAGER_URL=https://your-host/projects/TOKEN/your-project/
```

## MIME detection

Uploads use the [`file-type`](https://github.com/sindresorhus/file-type) package instead of `python-magic`. If a file is rejected as unknown type but worked on Python, inspect the magic bytes / extend allowed handling.

## Smoke tests

With a running server and real tokens:

```bash
BASE_URL=http://127.0.0.1:3000 MEDIA_TOKEN=... ADMIN_TOKEN=... \
  npm run test-api
```

## File layout

- `src/app/projects/...` — project API + SPA shell
- `src/app/admin/...` — admin API + dashboard shell
- `src/lib/` — DB (pg), S3, auth/Vault, shared helpers
- `public/mm/` — verbatim HTML + static assets from `remote/static/`
