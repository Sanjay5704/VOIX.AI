# Measurements log

Raw numbers from real runs, recorded as measured. Docs and resume bullets
must cite this file, not estimates. Each job's own metrics are also stored in
`jobs.result.metrics`.

**Definitions.** *Synthesis RTF* = model inference time / audio duration
(lower is faster; < 1 is faster than real time). *Total RTF* additionally
includes model loading (cold start only) and ffmpeg post-processing.

## 2026-10-28 — first end-to-end run, XTTS-v2

Hardware: NVIDIA GeForce RTX 4070 Laptop GPU (8 GB), Windows 11, on AC power.
Software: Python 3.11.0, torch 2.5.1+cu124, Coqui TTS 0.22.0, fp32, worker 0.2.0.
Setup: API on SQLite on the same machine; worker pulling over HTTP.
Voices: XTTS built-in studio speakers.

| Run | Chars | Chunks | Audio (s) | Model load (ms) | Synthesis (ms) | Synthesis RTF | Post-process (ms) | Total RTF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cold (Ana Florence) | 224 | 3 | 17.41 | 127,147 | 48,058 | 2.70 | 3,624 | 10.28 |
| warm (Damien Black) | 85 | 2 | 5.46 | 0 | 17,557 | 3.00 | 3,295 | 3.83 |
| warm (Damien Black) | 211 | 2 | 13.12 | 0 | 32,447 | 2.40 | 577 | 2.52 |

Observations:

- The pipeline worked end to end: the job was queued with no worker online,
  claimed on worker start, kept alive by lease heartbeats through a 127 s cold
  model load (lease is 60 s), and completed on the first attempt. Audio and
  SRT downloads required auth (401 without).
- XTTS-v2 is **slower than real time** on this setup (warm synthesis RTF
  2.4–3.0). GPU utilisation sampled at ~18 % with ~2.1 GB VRAM in use during
  synthesis, which suggests the autoregressive decode is CPU/launch bound
  rather than GPU bound. To investigate in the Phase 3 benchmark (fp16,
  inference settings, comparison with Kokoro on identical scripts).
- The cold model load (127 s) includes reading the checkpoint from `D:`;
  warm runs used a worker started with `--preload`, whose load time was not recorded.

## 2026-10-28 — Kokoro-82M on the same machine

Same hardware/software as above plus kokoro 0.9.4, misaki 0.9.4 (installed into
the same venv; `pip check` clean, TTS 0.22.0 untouched). Same 224-char script
for every run, 3 chunks.

| Run | Voice | Audio (s) | Model load (ms) | Synthesis (ms) | Synthesis RTF | Post-process (ms) | Total RTF |
|---|---|---:|---:|---:|---:|---:|---:|
| cold, `--once`, before warm-up fix | af_heart | 17.58 | 26,724 | 28,812 | 1.60 | 3,334 | 3.35 |
| cold, new worker process, before fix | af_heart | 17.58 | 14,111 | 15,926 | 0.89 | 704 | 1.75 |
| warm | af_heart | 17.58 | 0 | 1,137 | **0.063** | 623 | 0.100 |
| warm | af_heart | 17.58 | 0 | 1,100 | **0.061** | 665 | 0.101 |
| cold, after warm-up fix | bm_george | 19.53 | 27,685 | 4,023 | 0.20 | 702 | 1.66 |

Observations:

- Warm Kokoro synthesises ~16x faster than real time (synthesis RTF ~0.06);
  including ffmpeg post-processing it is ~10x (total RTF ~0.10).
- On the same script, warm Kokoro synthesis (1.1 s) vs warm XTTS-class runs
  (RTF 2.4–3.0) is roughly a 40x difference. This is not yet a controlled
  benchmark (different voices, few samples); Phase 3 repeats it properly.
- **Measurement bug found and fixed:** Kokoro's G2P pipeline setup and first
  CUDA call ran inside the first `synthesize_chunk`, so cold jobs reported a
  synthesis RTF of 0.89–1.60. The engine now builds its pipelines and runs a
  warm-up inference in `load()`, so that cost is reported as model load. The
  remaining cold overhead on the `bm_george` run is that voicepack's first fetch.

## 2026-10-28 — controlled benchmark, Kokoro vs XTTS (Phase 3)

Full report: [BENCHMARK.md](BENCHMARK.md); raw data:
`benchmarks/results/20261028T065315Z-Sanjay.json`. 6 fixed scripts × 3 repeats,
same pipeline as production, quality checked with `openai/whisper-small.en`.

| | Kokoro-82M | XTTS-v2 |
|---|---:|---:|
| Throughput (total audio ÷ total synthesis time) | **14.4× real time** | 1.5× real time |
| Median per-script synthesis RTF | 0.079 | 0.473 |
| Corpus WER / CER (Whisper round-trip) | **0.4% / 0.3%** | 2.3% / 1.4% |
| Peak VRAM above baseline | **747 MB** | 2,028 MB |
| Load + warm-up | 35.4 s | 102.5 s |
| Short line (46 chars) synthesis | 310 ms | 8,045 ms |

Observations:

- Kokoro is ~10× higher throughput than XTTS on this laptop, at a third of the
  VRAM, with fewer ASR errors. XTTS's value here is cloning, not speed.
- **XTTS latency is highly variable for identical input:** the 185-char
  explainer took 5.2 s, 17.3 s and 25.2 s across three repeats; the one-sentence
  script took 7.2–9.0 s. Kokoro's repeats agreed within a few percent. This is
  consistent with the earlier worker runs (RTF 2.4–3.0 on short multi-chunk
  scripts) being draws from the slow end of the same distribution. Likely
  cause (unverified): XTTS's sampled autoregressive decoder producing long token
  sequences on some draws.
- XTTS's highest WER was on the dialogue script (11.5%: short exclamations and
  questions); Kokoro's only errors were on the abbreviations script.
- Kokoro synthesis RTF measured in different sessions ranged 0.025–0.11 for
  similar text; single-session numbers are comparable, cross-session ones less so
  (laptop GPU boost/power management). The table above is one controlled run.

## 2026-10-28 — real load through the queue (analytics)

`scripts/loadgen.py --users 4 --jobs 40 --xtts-share 0.15` against the API +
one GPU worker (both engines preloaded). Result: 36 succeeded, 1 failed
(punctuation-only script, rejected as non-retryable), 3 canceled; one user hit
the 10 jobs/min rate limit and backed off per `Retry-After`.

From `/v1/analytics` (includes the day's earlier manual jobs):

| Engine | Finished jobs | Failure rate | Render p50 | Render p95 | Queue wait p50 | Queue wait p95 |
|---|---:|---:|---:|---:|---:|---:|
| kokoro | 42 | 2.6% | 830 ms | 40.2 s | 34.0 s | 51.5 s |
| xtts | 7 | 0.0% | 20.1 s | 178.9 s | 21.0 s | 35.2 s |

- **Head-of-line blocking:** Kokoro jobs render in under a second but waited a
  median 34 s, because a single worker processes the queue in order and the
  burst's XTTS jobs (≈20 s each) sat in front of them. Fixes, not yet built:
  run one worker per engine, or prefer short/fast-engine jobs when claiming.
- The p95 render times are the day's cold-start jobs (first Kokoro job after a
  worker start: 40 s; first XTTS job: 179 s), which is why workers now support
  `--preload`.

## 2026-10-28 — head-of-line blocking fixed with per-engine lanes

The worker now runs one claim loop per engine (`LANES=per-engine`, the default),
so a Kokoro job no longer waits behind XTTS jobs. Same load as before
(`scripts/loadgen.py --users 4 --jobs 40 --xtts-share 0.15`, seed 7; same
outcome: 36 succeeded, 1 failed, 3 canceled). Queue wait = enqueue → claim,
nearest-rank percentiles over that run's jobs.

| | Before (one loop) | After (per-engine lanes) |
|---|---:|---:|
| Kokoro queue wait p50 | 34.0 s | **2.2 s** |
| Kokoro queue wait p95 | 51.5 s | **5.1 s** |
| XTTS queue wait p50 | 15.5 s | 12.8 s |
| Kokoro render p50 | 0.78 s | 0.86 s |
| XTTS render p50 (n=4) | 7.87 s | 10.74 s |

The cost is GPU sharing: renders are somewhat slower while both engines run
at once (XTTS n=4 is small and within its normal run-to-run spread). The old
behaviour remains available with `LANES=shared`.
