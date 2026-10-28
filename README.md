# VOIX — AI voiceover studio + developer TTS API

Paste a script → pick or clone a voice → get a voiceover with SRT subtitles,
plus job history. The same engine is exposed as a REST API with API keys,
quotas and usage metering.

> **Status:** control plane, queue and GPU worker; React dashboard; engine
> benchmarks and analytics are done. CI and free-tier deployment are next.
> See [docs/RUNNING.md](docs/RUNNING.md) to run it.

## Architecture (short version)

```
 browser / API client ──HTTPS──▶  FastAPI control plane  ──▶  Postgres  (users, keys, voices, jobs = queue, usage, audit)
                                        │      ▲                └──▶  object storage (local disk or S3/R2)
                                        │      │ claim / heartbeat / complete   (outbound HTTPS only)
                                        ▼      │
                                   GPU worker on a laptop (XTTS-v2 / Kokoro / mock)
```

- **Async jobs.** `POST /v1/jobs/tts` returns `202` at once. Rendering happens on a worker.
- **Pull-based worker.** The worker makes only outbound requests, so it works behind home NAT.
  While it is off, jobs stay `queued` and `/v1/health` reports the worker offline.
- **Queue in Postgres, no Redis.** Claims use `SELECT … FOR UPDATE SKIP LOCKED`. Jobs carry
  leases that worker heartbeats extend; expired leases are reaped lazily (requeue until
  `max_attempts`, then fail). Retries back off exponentially. Cancellation is cooperative.
- **Auth.** JWT for the dashboard, `vx_live_…` API keys (stored as sha256) for developers.
  Workers use a separate token.
- **Limits.** Monthly character quotas per plan and per-user rate limits. Both are computed from
  the database, so they hold across API instances. `Idempotency-Key` makes retries safe.
- **Voice cloning is consent-gated.** Uploads require an explicit consent statement, which is
  stored with the voice and written to an audit log.
- **Separate packages.** `api/` has no torch dependency; `worker/` has no SQLAlchemy dependency.

```
api/        FastAPI control plane, SQLAlchemy 2.0 models, Alembic migrations, tests
worker/     GPU worker: engines, synthesis pipeline (chunking, pauses, pitch, speed, loudnorm, SRT)
frontend/   React dashboard: studio, history, voice library + consent flow, API keys, usage
tests_e2e/  API + queue + worker in one process with the mock engine
benchmarks/ multi-engine benchmark: latency, RTF, VRAM, Whisper round-trip WER/CER
scripts/    legacy voice import, load generator
docs/       RUNNING.md, BENCHMARK.md (generated), ANALYTICS.md, MEASUREMENTS.md
```

## Measured on an RTX 4070 Laptop GPU

From [docs/BENCHMARK.md](docs/BENCHMARK.md) (6 scripts × 3 repeats, Whisper round-trip):

| Engine | Throughput | WER | Peak VRAM |
|---|---:|---:|---:|
| Kokoro-82M | 14.4× real time | 0.4% | 747 MB |
| XTTS-v2 | 1.5× real time | 2.3% | 2,028 MB |

## Engines and licences

| Engine | Licence | Commercial use | Cloning | Role |
|---|---|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0 (weights) | Yes | No, fixed voicepacks | Default engine |
| [Coqui XTTS-v2](https://huggingface.co/coqui/XTTS-v2) | Coqui Public Model License 1.0 | **No** (non-commercial only) | Yes, 3–60 s reference | Cloning / demo |
| Mock | Project code | Yes | Yes (ignored) | Tests and CI |

Coqui (the company) has shut down, so a commercial XTTS licence can no longer be
obtained. Any deployment that charges users must disable XTTS
(`ENABLED_ENGINES=kokoro`). This project is a portfolio demo and does not charge anyone.

Only clone voices you have explicit permission to use.

## Licence

No licence has been chosen for the project code yet (all rights reserved until one is added).
Model weights keep their own licences (above).
