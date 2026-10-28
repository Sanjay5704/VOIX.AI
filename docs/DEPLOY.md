# Deploying VOIX on free tiers (₹0/month)

| Piece | Service (free tier) | Notes |
|---|---|---|
| API | **Render** web service (Docker) | Sleeps after ~15 min without requests; the worker's polling keeps it awake while your laptop is on. |
| Postgres | **Neon** | 0.5 GB storage is plenty for job metadata. |
| Audio files | **Cloudflare R2** | 10 GB storage, no egress fees. Downloads use presigned URLs. |
| Dashboard | **Cloudflare Pages** | Static build with SPA fallback and security headers generated at build time. |
| GPU worker | **Your laptop** | Pulls jobs over HTTPS; no ports to open. |

You create the accounts and paste the secrets; nothing in the repo contains them.

## 1. Postgres (Neon)

1. Create a project → copy the connection string (`postgresql://...?sslmode=require`).
2. That's the API's `DATABASE_URL`. The API adds the psycopg driver itself and runs
   `alembic upgrade head` on every start.

## 2. Storage (Cloudflare R2)

1. Create a bucket, e.g. `voix-audio`.
2. R2 → *Manage API tokens* → create a token with **Object Read & Write** on that bucket.
   Note the access key id, secret, and the S3 endpoint `https://<account-id>.r2.cloudflarestorage.com`.
3. Bucket → *Settings* → *CORS policy* (lets the browser follow presigned download redirects):

```json
[{ "AllowedOrigins": ["https://<your-project>.pages.dev"], "AllowedMethods": ["GET"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600 }]
```

## 3. API (Render)

1. Render → *New* → *Blueprint* → pick this repo (uses `render.yaml`).
2. Fill the prompted values: `DATABASE_URL`, `S3_BUCKET`, `S3_ENDPOINT_URL`,
   `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `CORS_ORIGINS` (your Pages URL).
   `JWT_SECRET`, `WORKER_TOKEN` and `METRICS_TOKEN` are generated.
3. After the deploy: `https://<service>.onrender.com/v1/health` should return
   `{"status":"degraded", "workers_online":0, ...}` (no worker yet).

## 4. Dashboard (Cloudflare Pages)

1. Pages → connect the repo. Root directory `frontend`, build command
   `npm ci && npm run build`, output `dist`.
2. Environment variable `VITE_API_BASE_URL=https://<service>.onrender.com`.
   The build writes `_headers` (CSP allowing that API and R2) and `_redirects` (SPA routes).

## 5. GPU worker (your laptop)

`worker/.env`:

```
API_URL=https://<service>.onrender.com
WORKER_TOKEN=<copy from Render → Environment>
WORKER_NAME=rtx4070-laptop
ENGINES=kokoro,xtts
```

```powershell
cd worker
..\env\Scripts\python -m voix_worker --preload
```

The dashboard's lamp switches to **On air**. Close the worker and jobs queue
until it comes back.

## 6. Operator access and benchmarks

Run admin commands from your laptop against the production database:

```powershell
cd api
$env:DATABASE_URL = "<Neon connection string>"
.\.venv\Scripts\python -m voix_api.admin promote you@example.com
Remove-Item Env:DATABASE_URL
```

Publish a benchmark run to production:

```powershell
$env:WORKER_TOKEN = "<token>"
.\env\Scripts\python -m benchmarks.run_benchmark --upload-file benchmarks\results\<file>.json --api-url https://<service>.onrender.com
```

## Monitoring

- `GET /metrics` (Prometheus format) needs `Authorization: Bearer <METRICS_TOKEN>`.
  It exposes HTTP rate/latency by route, jobs created/finished by engine and status,
  processing-time histograms, queue depth per engine, and workers online. Grafana
  Cloud's free tier can scrape it.
- Logs are JSON lines with a `request_id`; every response carries `X-Request-ID`,
  and error bodies include it.

## Licence reminder

XTTS-v2 is non-commercial (Coqui Public Model License). For anything that charges
users, set `ENABLED_ENGINES=kokoro`.
