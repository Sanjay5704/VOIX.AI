# syntax=docker/dockerfile:1
#
# XTTS-v2 TTS Backend
#
# Build (GPU host, CUDA base image with NVIDIA Container Toolkit installed):
#   docker build -t xtts-backend .
# Build (CPU-only):
#   docker build --build-arg BASE_IMAGE=python:3.11-slim -t xtts-backend .
#
ARG BASE_IMAGE=nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COQUI_TOS_AGREED=1 \
    PIP_NO_CACHE_DIR=1

# --- System dependencies ---
# ffmpeg: required audio processing engine (speed/pitch/format conversion)
# python3/pip: base interpreter (CUDA base image doesn't ship one).
#   Ubuntu 22.04's default apt repo ships Python 3.10, which is what we use
#   here rather than pinning 3.11 via the deadsnakes PPA, to keep the build
#   reproducible without adding third-party apt sources.
# libsndfile1: required by soundfile
# espeak-ng: phonemizer backend used by some Coqui TTS models
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ffmpeg \
        libsndfile1 \
        espeak-ng \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r requirements-ml.txt

COPY . .

RUN mkdir -p voices outputs uploads logs model_cache voices/custom

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
