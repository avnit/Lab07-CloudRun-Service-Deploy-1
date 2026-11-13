# =====================================================================
# INTENTIONALLY VULNERABLE IMAGE - LAB / SANDBOX USE ONLY.
# CM-0004 / CWE-1104: python:3.8-slim-buster is an end-of-life base
# image (Python 3.8 and Debian 10 "buster" no longer get security fixes).
# Expected fix: move to a supported base, e.g. python:3.12-slim-bookworm.
# =====================================================================
FROM python:3.8-slim-buster

LABEL org.opencontainers.image.title="antigravity-hermes-watchlist"
LABEL org.opencontainers.image.description="Watch Next: intentionally vulnerable lab app. Do not deploy to production."

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/watchlist

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY web/ web/
COPY data/ data/
COPY scripts/fetch_media.py scripts/fetch_media.py

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /srv/watchlist/data
USER appuser

# Cloud Run sends traffic to PORT (default 8080). One worker: the app seeds
# the database on start-up, and the MySQL sidecar is per instance.
ENV HOST=0.0.0.0 \
    PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 120 'app.main:create_app()'"]
