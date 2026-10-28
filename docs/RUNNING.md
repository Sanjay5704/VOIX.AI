# Running VOIX locally (Windows / PowerShell)

Three processes: **Postgres** (or SQLite for a quick start), the **API**, and
the **GPU worker**. The worker only makes outbound HTTP(S) calls to the API, so
it can sit behind home NAT; when it is off, jobs simply wait in the queue and
`GET /v1/health` reports `degraded` with `workers_online: 0`.

All commands run from the repo root (`D:\Programs Files\VOIX.AI`).

## 1. API

One-time setup:

```powershell
py -3.11 -m venv api\.venv
api\.venv\Scripts\python -m pip install -r api\requirements-dev.txt
Copy-Item api\.env.example api\.env
```

**Database — option A: SQLite (no Docker needed).** Edit `api\.env`:

```
DATABASE_URL=sqlite:///./data/voix.sqlite3
```

**Database — option B: Postgres in Docker** (needs Docker Desktop with WSL 2):

```powershell
docker compose up -d postgres     # Postgres 16 on localhost:5433, user/pass voix/voix
```

The default `DATABASE_URL` in `.env.example` already points at it.

Migrate and start:

```powershell
cd api
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn voix_api.main:app --port 8000
```

Swagger UI: <http://localhost:8000/docs>. System voices for the enabled
engines are seeded on startup.

## 2. GPU worker (RTX laptop, existing `.\env`)

One-time setup (adds the worker's small dependencies to the existing venv
that already has torch + Coqui TTS):

```powershell
.\env\Scripts\python -m pip install -r worker\requirements.txt
Copy-Item worker\.env.example worker\.env
```

Run it (in a second terminal):

```powershell
cd worker
..\env\Scripts\python -m voix_worker --engines xtts --preload
```

- `--engines mock` runs the full pipeline with generated tones (no GPU, no model download).
- `--once` processes a single job and exits.
- **Ctrl+C** releases the current job back to the queue without spending a retry
  attempt; a second Ctrl+C exits immediately (the lease then expires and the API
  requeues the job).

The first XTTS job downloads the model (~1.8 GB) into the Coqui cache and you
must accept the Coqui Public Model License (non-commercial). The worker sets
`COQUI_TOS_AGREED=1` for non-interactive runs, which means *you* are agreeing to it.

## 3. Dashboard

```powershell
cd frontend
npm ci          # once
npm run dev     # http://localhost:5173  (proxies /v1 to the API on :8000)
```

Register an account, then use Studio → render. The **On air** lamp in the top
bar shows whether a GPU worker is connected; with the worker off, renders queue
and start automatically when it comes back. Production build: `npm run build`
(set `VITE_API_BASE_URL` if the API is on a different origin).

## 4. Try it with curl (PowerShell)

```powershell
$base = "http://localhost:8000"
$reg = Invoke-RestMethod "$base/v1/auth/register" -Method Post -ContentType "application/json" `
  -Body '{"email":"me@example.com","password":"a long password"}'
$h = @{ Authorization = "Bearer $($reg.access_token)" }

$voice = (Invoke-RestMethod "$base/v1/voices" -Headers $h | Where-Object name -eq "Ana Florence").id
$job = Invoke-RestMethod "$base/v1/jobs/tts" -Method Post -Headers ($h + @{ "Idempotency-Key" = "demo-1" }) `
  -ContentType "application/json" -Body (@{ voice_id = $voice; text = "Hello from VOIX." } | ConvertTo-Json)

# poll until succeeded, then download
Invoke-RestMethod "$base/v1/jobs/$($job.id)" -Headers $h
Invoke-WebRequest "$base/v1/jobs/$($job.id)/audio" -Headers $h -OutFile voix.mp3
Invoke-WebRequest "$base/v1/jobs/$($job.id)/subtitles" -Headers $h -OutFile voix.srt
```

Developer API keys: `POST /v1/api-keys` (shown once), then send `X-API-Key: vx_live_...`
instead of the Bearer header.

## 5. Re-import voices from the old app

The pre-SaaS app's cloned voices in `backend\voices\custom\` can be uploaded to
your account (consent-gated and audit-logged like any clone; files on disk are
not modified). Needs a running worker with a cloning engine to prepare them.

```powershell
api\.venv\Scripts\python scripts\import_legacy_voices.py --email me@example.com --i-have-consent
```

## 6. Benchmarks and analytics

```powershell
# Benchmark engines on this GPU (writes benchmarks/results/*.json + docs/BENCHMARK.md)
.\env\Scripts\python -m benchmarks.run_benchmark --engines kokoro,xtts --repeats 3

# Publish the latest run to a running API (shows on the Benchmarks page and /v1/engines)
.\env\Scripts\python -m benchmarks.run_benchmark --upload-file benchmarksesults\<file>.json

# Grant yourself access to the Analytics page
cd api; .\.venv\Scripts\python -m voix_api.admin promote me@example.com; cd ..

# Generate real traffic through the queue (needs API + worker running)
api\.venv\Scripts\python scripts\loadgen.py --users 4 --jobs 40

# Inspect the analytics SQL as rendered for your database
cd api; .\.venv\Scripts\python -m voix_api.analytics show fct_engine_daily; cd ..
```

The first benchmark run downloads `openai/whisper-small.en` (~1 GB) for the
quality check. See [ANALYTICS.md](ANALYTICS.md) for the data models.

## 7. Tests

```powershell
# API (SQLite)
cd api; .\.venv\Scripts\python -m pytest; cd ..

# API against Postgres (runs the Alembic migrations + concurrent SKIP LOCKED claims)
$env:TEST_DATABASE_URL = "postgresql+psycopg://voix:voix@localhost:5433/voix_test"
cd api; .\.venv\Scripts\python -m pytest; cd ..
Remove-Item Env:TEST_DATABASE_URL

# Worker (needs ffmpeg on PATH)
cd worker; ..\env\Scripts\python -m pytest -p no:asyncio; cd ..

# Benchmark metrics (WER/CER)
api\.venv\Scripts\python -m pytest benchmarks

# End to end: API + queue + worker (mock engine) in one process
api\.venv\Scripts\python -m pip install -r worker\requirements.txt   # once
api\.venv\Scripts\python -m pytest tests_e2e

# Frontend production build
cd frontend; npm run build; cd ..

# Lint / format
api\.venv\Scripts\ruff check api worker tests_e2e scripts
api\.venv\Scripts\ruff format --check api worker tests_e2e scripts
```

## Full stack in Docker

```powershell
docker compose up --build                      # postgres + api + web
docker compose --profile worker up --build     # + CPU mock worker
```

The real GPU worker is meant to run natively (above) so it uses the host's CUDA.
