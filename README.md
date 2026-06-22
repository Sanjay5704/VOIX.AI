# NaturalSpeech — Production Text-to-Speech Application

A complete, production-ready text-to-speech system built on **Coqui XTTS-v2**
(state-of-the-art open-source multilingual, voice-cloning-capable TTS),
served through a **FastAPI** backend and a **React** frontend.

It generates natural, expressive speech — proper pauses at punctuation,
correct handling of abbreviations and sentence boundaries, adjustable
speed/pitch, optional emotion-leaning delivery, two built-in voices
(Male / Female), on-the-fly voice cloning from an uploaded sample,
per-sentence timestamps, `.srt` subtitle export, batch processing, and
WAV/MP3 export — running entirely locally on a consumer GPU or CPU.

---

## Project layout

```
xtts-app/
├── backend/                  FastAPI + XTTS-v2 TTS engine
│   ├── app/
│   │   ├── api/               Route handlers (tts, voices, health)
│   │   ├── core/               Config, logging, exceptions
│   │   ├── models/              Pydantic request/response schemas
│   │   ├── services/             TTS engine, voice registry, cloning, batch
│   │   ├── utils/                  Text processing, audio (ffmpeg), SRT, files
│   │   └── main.py                  FastAPI app entrypoint
│   ├── tests/                Unit + API tests (pytest)
│   ├── voices/                Reference speaker clips (male/female/custom)
│   ├── outputs/                 Generated audio/subtitle files (runtime)
│   ├── uploads/                   Temp upload staging (runtime)
│   ├── logs/                       Rotating log files (runtime)
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/                  React (Vite) single-page app
│   ├── src/
│   │   ├── components/         UI components
│   │   ├── hooks/                Data/state hooks
│   │   ├── services/              API client
│   │   └── styles/                  Design system CSS
│   ├── package.json
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml        Full stack, GPU by default
├── docker-compose.cpu.yml    CPU-only override
└── docs/
    ├── INSTALL.md             Step-by-step setup (local + Docker)
    └── API.md                  Full API reference
```

## Quick start

See **[docs/INSTALL.md](docs/INSTALL.md)** for full setup instructions,
including GPU driver setup, FFmpeg installation, and voice customization.

**Fastest path (Docker, GPU):**

```bash
git clone <this-repo>
cd xtts-app
cp backend/.env.example backend/.env
docker compose up --build
```

Then open **http://localhost:3000**.

**Fastest path (Docker, CPU-only):**

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```

## Core technology choices

| Concern | Choice | Why |
|---|---|---|
| TTS model | Coqui **XTTS-v2** | Best open-source quality/latency tradeoff; native zero-shot voice cloning; 17-language multilingual support; runs on consumer GPUs (8GB+) or CPU |
| Backend | **FastAPI** | Async-first, typed (Pydantic), auto-generated OpenAPI docs, production-grade |
| Frontend | **React** (Vite) | Fast dev loop, component-driven UI, no server dependency for the SPA |
| Audio processing | **FFmpeg** | Industry-standard, reliable speed/pitch/format conversion without re-synthesis |
| Natural prosody | Sentence-level chunking + punctuation-aware pause insertion | XTTS quality degrades on long inputs; per-sentence synthesis + inserted silence mimics human breath/pause patterns |

## Key design decisions worth knowing

- **Sentence-level synthesis, not whole-paragraph.** Text is normalized,
  split into sentences, and (if still too long) sub-chunked on clause
  boundaries. Each chunk is synthesized independently, then concatenated
  with a punctuation-aware silence gap (longer after `.`/`!`/`?`, shorter
  after `,`/`;`). This is what gives the output natural cadence instead of
  a rushed, robotic run-on — and it's also what makes accurate per-sentence
  timestamps (and therefore `.srt` subtitles) possible.
- **Speed and pitch are post-processed via FFmpeg**, not only via XTTS's
  internal `speed` parameter — this decouples the two controls and keeps
  pitch-shifting independent of tempo (asetrate + compensating atempo
  chain, no external rubberband plugin dependency).
- **Device auto-detection.** On startup the backend detects CUDA
  availability and VRAM, enabling fp16 only when there's enough headroom,
  and transparently falls back to CPU with no code changes needed.
- **Voice cloning is zero-shot.** No fine-tuning step — XTTS conditions
  generation on a short reference clip (3-60s) at inference time.

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

The test suite covers text normalization/sentence-splitting, SRT
generation, and full API routing/validation/error-handling — the API
tests mock the XTTS engine itself so they run in seconds without
downloading model weights.

## License notes

Coqui XTTS-v2 is distributed under the **Coqui Public Model License**,
which permits non-commercial use freely; commercial use requires a
separate license from Coqui. Review the license terms before deploying
commercially. See `docs/INSTALL.md` for details and links.
