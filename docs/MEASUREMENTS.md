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
