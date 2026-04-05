FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE.md ./
RUN mkdir -p boomarr && touch boomarr/__init__.py boomarr/py.typed \
    && pip install --no-cache-dir . \
    && rm -rf boomarr

COPY boomarr/ ./boomarr/
RUN pip install --no-cache-dir --no-deps .

RUN groupadd -g 1000 boomarr \
    && useradd -u 1000 -g boomarr -m --no-log-init boomarr \
    && mkdir -p /config \
    && chown boomarr:boomarr /app /config

ENV PUID=1000
ENV PGID=1000
ENV UMASK=022
ENV TZ=UTC
ENV CONFIG_DIR=/config
ENV LOG_DIR=/config/logs

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

VOLUME /config

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["boomarr", "--help"]
