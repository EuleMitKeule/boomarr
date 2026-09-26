# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14

# Statically linked ffprobe (amd64 + arm64). Boomarr only needs ffprobe, so
# this avoids pulling the full Debian ffmpeg package and its ~400 MB of
# shared libraries into the image.
FROM mwader/static-ffmpeg:9.0 AS ffmpeg

FROM ghcr.io/astral-sh/uv:0.12 AS uv

# ---------------------------------------------------------------------------
# Web UI: static files only, the runtime image contains no Node.js
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

# ---------------------------------------------------------------------------
# Build stage: resolve dependencies strictly from uv.lock
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md LICENSE.md ./
COPY boomarr ./boomarr
COPY --from=frontend /src/boomarr/web/dist ./boomarr/web/dist

ARG VERSION=0.0.0-dev
RUN --mount=type=cache,target=/root/.cache/uv \
    sed -i "s/0\.0\.0-dev/${VERSION}/g" pyproject.toml boomarr/const.py \
    && uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="Boomarr" \
      org.opencontainers.image.description="Symlink-based audio language filter for Plex, Jellyfin & Emby" \
      org.opencontainers.image.source="https://github.com/EuleMitKeule/boomarr" \
      org.opencontainers.image.documentation="https://github.com/EuleMitKeule/boomarr#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 boomarr \
    && useradd -u 1000 -g boomarr -M -d /config -s /usr/sbin/nologin --no-log-init boomarr \
    && mkdir -p /config \
    && chown boomarr:boomarr /config

COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
COPY --from=builder /opt/venv /opt/venv
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PUID=1000 \
    PGID=1000 \
    UMASK=022 \
    TZ=UTC \
    CONFIG_DIR=/config \
    LOG_DIR=/config/logs \
    HEARTBEAT_FILE=/tmp/boomarr.heartbeat

VOLUME /config
EXPOSE 9797

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["boomarr", "healthcheck"]

ENTRYPOINT ["tini", "--", "/docker-entrypoint.sh"]
CMD ["boomarr", "watch"]
