# syntax=docker/dockerfile:1
# CPU worker image running the mock engine (demo/CI). The real GPU worker runs
# natively on the host so it can use the local CUDA install.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY voix_worker ./voix_worker
RUN useradd --create-home --uid 10001 voix && mkdir -p /app/cache && chown voix /app/cache
USER voix
CMD ["python", "-m", "voix_worker"]
