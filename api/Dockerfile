# syntax=docker/dockerfile:1
# VOIX control-plane API. Small image: no torch, no ffmpeg.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY voix_api ./voix_api

RUN useradd --create-home --uid 10001 voix && mkdir -p /app/data && chown voix /app/data
USER voix

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

# Migrate, then serve. PORT is set by most PaaS hosts.
CMD ["sh", "-c", "alembic upgrade head && uvicorn voix_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
