# Installation Guide

Two paths: **Docker** (recommended, fastest, most reproducible) or
**manual local setup** (best for active development / debugging).

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10 or 3.11 | XTTS-v2 / Coqui TTS does not yet support 3.12 reliably for all dependencies |
| Node.js 18+ and npm | For the React frontend |
| FFmpeg | Required for all audio post-processing (speed/pitch/format/SRT timing) |
| (Optional) NVIDIA GPU + CUDA 12.x + drivers | 8GB+ VRAM recommended for real-time-ish generation. CPU works but is slower. |
| (Optional) Docker + Docker Compose | For containerized deployment |
| (Optional) NVIDIA Container Toolkit | Only needed for GPU acceleration inside Docker |

### Installing FFmpeg

```bash
# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# macOS (Homebrew)
brew install ffmpeg

# Windows (Chocolatey)
choco install ffmpeg
```

Verify: `ffmpeg -version` and `ffprobe -version` should both print a version.

---

## 2. Manual local setup

### 2.1 Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# Edit .env if you want to change ports, device preference, limits, etc.
```

**Important — Coqui TTS license prompt:** the first time XTTS-v2 downloads,
Coqui TTS will normally ask you to interactively accept its model license.
For non-interactive/server use, the `.env.example` already sets
`COQUI_TOS_AGREED=1` to bypass this prompt — make sure you've actually
read and agree to the license before doing so (see "Licensing" below).

Run the server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On first startup:
1. The app ensures `voices/male_default.wav` and `voices/female_default.wav`
   exist, generating lightweight placeholders via `pyttsx3` if you haven't
   supplied your own (see "Customizing Default Voices" below).
2. XTTS-v2 model weights (~1.8GB) download automatically to
   `model_cache/` / the Coqui TTS cache directory on first load. This can
   take a few minutes depending on your connection.
3. The model loads onto GPU (if detected) or CPU automatically.

Check it's healthy:

```bash
curl http://localhost:8000/api/v1/health
```

API docs are auto-served at **http://localhost:8000/docs** (Swagger UI)
and **http://localhost:8000/redoc**.

### 2.2 Frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env     # optional — defaults work for local dev via the Vite proxy
npm run dev
```

Open **http://localhost:3000**. The Vite dev server proxies `/api/*`
requests to `http://localhost:8000` automatically (see `vite.config.js`).

### 2.3 Production build (manual, no Docker)

```bash
cd frontend
npm run build
# Serve frontend/dist with any static file server, e.g.:
npx serve dist -p 3000
# Or copy frontend/dist into the document root of nginx/Apache and point
# /api/ at your backend host.
```

For the backend in production, run with multiple workers is **not**
recommended for the TTS endpoint specifically (the model lives in GPU/CPU
memory per-process, so multiple workers multiply memory usage). Instead,
keep `--workers 1` and rely on the internal generation semaphore
(`MAX_CONCURRENT_GENERATIONS` in `.env`) to queue concurrent requests
safely. Put a reverse proxy (nginx) in front for TLS termination.

---

## 3. Docker setup

### 3.1 GPU (default)

Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed on the host.

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000

### 3.2 CPU-only

```bash
cp backend/.env.example backend/.env
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up --build
```

This swaps the backend base image to `python:3.11-slim` (no CUDA
toolkit/runtime layers) and forces `DEVICE_PREFERENCE=cpu`. Expect
generation to take noticeably longer per sentence than on GPU.

### 3.3 Persisted volumes

The compose file defines named volumes for `voices`, `outputs`,
`uploads`, `logs`, and `model_cache` so cloned voices and the downloaded
model survive container restarts/rebuilds. To fully reset:

```bash
docker compose down -v
```

---

## 4. Customizing the default Male/Female voices

Out of the box, the app bootstraps placeholder reference clips using your
OS's built-in TTS voices via `pyttsx3` purely so the app works
immediately without manual setup. **These placeholders are not
high-quality** — for the natural, human-sounding output XTTS-v2 is
capable of, replace them:

1. Record (or source) two clean, single-speaker, single-language audio
   clips, 6–15 seconds each, minimal background noise/reverb, natural
   speaking pace, WAV format.
2. Save them as:
   - `backend/voices/male_default.wav`
   - `backend/voices/female_default.wav`
3. Restart the backend. The bootstrap step only triggers when these
   files are missing, so your files won't be overwritten.

You can also clone additional voices at runtime through the UI ("+ Clone
a voice") or via `POST /api/v1/voices/clone` — see `docs/API.md`.

---

## 5. Hardware sizing guidance

| Setup | Expected behavior |
|---|---|
| RTX 3060/3070/4060 (8-12GB VRAM) | Good — near-real-time per-sentence generation, fp16 enabled automatically |
| RTX 4090 / A-series (16GB+ VRAM) | Fast — can safely raise `MAX_CONCURRENT_GENERATIONS` |
| CPU only (modern 8+ core) | Functional but slow — expect several seconds per sentence; fine for batch/offline use, not snappy interactive use |
| <4GB VRAM | App will auto-disable fp16; consider `DEVICE_PREFERENCE=cpu` instead for stability |

---

## 6. Troubleshooting

**`ModuleNotFoundError: No module named 'TTS'`**
Re-run `pip install -r requirements.txt` inside the activated venv.

**`ffmpeg: command not found` / `FFmpegNotFoundError`**
Install FFmpeg (see step 1) and ensure it's on your `PATH`. Restart your
terminal/IDE after installing.

**Model download is slow or fails**
XTTS-v2 weights are downloaded from Hugging Face on first run. If you're
behind a restrictive network, pre-download the model on a machine with
better connectivity and copy the Coqui TTS cache directory
(`~/.local/share/tts` on Linux, see Coqui TTS docs for your OS) into the
target machine before first run.

**CUDA out of memory**
Lower `MAX_CONCURRENT_GENERATIONS` to `1` (default), close other
GPU-using processes, or set `DEVICE_PREFERENCE=cpu` in `.env`.

**Generated audio sounds choppy or has unnatural pauses**
This is usually a punctuation issue in the input text — see
`app/utils/text_processing.py` for how pauses map to punctuation. Very
long unpunctuated text will be hard-wrapped on word boundaries, which can
sound less natural; add commas/periods where natural breaks should occur.

**Voice cloning result doesn't sound like the source**
Use a longer, cleaner reference clip (15-30s ideal), free of background
music/noise/multiple speakers, and matching the target language.

---

## 7. Licensing note

This project uses **Coqui XTTS-v2**, distributed under the Coqui Public
Model License (CPML). Non-commercial use is broadly permitted; commercial
deployment requires reviewing and complying with the CPML terms (and
potentially a commercial license from Coqui). Review
https://coqui.ai/cpml before deploying this application commercially.
