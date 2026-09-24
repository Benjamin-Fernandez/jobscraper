# syntax=docker/dockerfile:1
#
# JobScraper v2 image (PRD section 8.6, M10-T1).
#
# Two stages. `web` builds the Vue bundle with node; `runtime` is a slim Python
# image that copies only the built files out of it, so node never reaches the
# final image. State lives in /app/data, which docker-compose.yml mounts as a
# named volume: the container is disposable, the database is not.
#
#   docker build -t jobscraper .
#   docker run --rm jobscraper python -m jobscraper doctor
#
# Layout: config.py finds the project root as the parent of `src/`, so with the
# code at /app/src the root is /app, the config is /app/config/config.yaml and
# every `data/...` path in it resolves to /app/data - the volume.

# ---------------------------------------------------------------- web bundle
FROM node:22-slim AS web
WORKDIR /build/web
# Lockfile first, so the dependency layer is cached until it changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# vite.config.js writes to ../src/jobscraper/web/static, i.e. /build/src/...
RUN npm run build

# ------------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    # Inside the container the server must listen on all interfaces, or Docker's
    # port mapping cannot reach it. Exposure on the HOST is decided by the
    # publish rule, which docker-compose.yml pins to 127.0.0.1 (PRD R-9).
    JOBSCRAPER_HOST=0.0.0.0 \
    JOBSCRAPER_PORT=8765

WORKDIR /app

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app \
            --shell /usr/sbin/nologin app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/
COPY --from=web /build/src/jobscraper/web/static/ ./src/jobscraper/web/static/

# The only writable path. A named volume mounted here starts as a copy of this
# directory, ownership included, so the non-root user can write to it.
RUN mkdir -p /app/data && chown app:app /app/data

USER app

EXPOSE 8765

# Probes the SPA root; stdlib only, since the slim image has no curl.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('JOBSCRAPER_PORT', '8765'), timeout=4)"]

CMD ["python", "-m", "jobscraper", "web"]
